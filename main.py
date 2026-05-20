from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.text import Text

# Load .env from the current working directory (or any parent) before anything else.
# Existing shell env vars take precedence; override=False preserves them.
load_dotenv(override=False)

console = Console(stderr=True)


def _check_env() -> None:
    """Fail fast with a helpful message if required env vars are missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY is not set.\n\n"
            "  [dim]export ANTHROPIC_API_KEY='sk-ant-...'[/dim]\n\n"
            "Get a key at [link=https://console.anthropic.com]console.anthropic.com[/link]",
            highlight=False,
        )
        sys.exit(1)

    if not os.environ.get("GITHUB_TOKEN"):
        console.print(
            "[yellow]Warning:[/yellow] GITHUB_TOKEN is not set. "
            "GitHub rate limits will be 60 req/hr (unauthenticated) instead of 5 000.\n"
            "  [dim]export GITHUB_TOKEN='ghp_...'[/dim]",
            highlight=False,
        )


def _repo_slug(repo_url: str) -> str:
    """Stable filename-safe slug derived from the repo URL."""
    clean = repo_url.rstrip("/").replace("https://github.com/", "").replace("/", "_")
    h = hashlib.sha1(repo_url.encode()).hexdigest()[:6]
    return f"{clean}_{h}"


@click.command()
@click.argument("repo_url")
@click.option("--output", "-o", default=None, help="Output HTML path (default: <project_name>_report.html)")
@click.option("--thinking-budget", default=8000, show_default=True, help="Extended thinking token budget")
@click.option("--cache-dir", default=".agent_cache", show_default=True, help="Directory to cache analysis JSON")
@click.option("--verbose", "-v", is_flag=True, help="Print fetcher stats and thinking token counts")
@click.option("--dry-run", is_flag=True, help="Show what would be fetched, then exit")
def cli(
    repo_url: str,
    output: str | None,
    thinking_budget: int,
    cache_dir: str,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Analyse a GitHub repository and produce an interactive HTML learning document."""

    _check_env()

    if dry_run:
        _dry_run(repo_url)
        return

    cache_path = pathlib.Path(cache_dir) / f"{_repo_slug(repo_url)}.json"
    analysis = None

    # ── Load from cache ───────────────────────────────────────────────────────
    if cache_path.exists():
        console.print(f"[dim]Loading cached analysis from {cache_path}[/dim]")
        try:
            from agent.models import AnalysisOutput
            raw = json.loads(cache_path.read_text())
            analysis = AnalysisOutput.model_validate(raw)
            console.print("[green]✓ Cache hit — skipping fetch and analysis[/green]")
        except Exception as exc:
            console.print(f"[yellow]Cache invalid ({exc}), re-running[/yellow]")
            analysis = None

    # ── Fetch + Analyse ───────────────────────────────────────────────────────
    if analysis is None:
        console.print(f"[bold]Analysing[/bold] [cyan]{repo_url}[/cyan]")
        console.print(f"[dim]Model: claude-haiku-4-5 · thinking budget: {thinking_budget:,} tokens[/dim]")

        start = time.monotonic()

        # Phase 1: fetch repo content (no model)
        with Live(console=console, refresh_per_second=4) as live:
            live.update(Text.from_markup("⟳ [cyan]Fetching repository content…[/cyan]"))
            from agent.fetcher import fetch_repo
            ctx = fetch_repo(repo_url)

        n_files = len(ctx.key_files)
        n_tree = len(ctx.file_tree)
        console.print(
            f"[dim]Fetched {n_files} key files · {n_tree} tree entries · "
            f"{len(ctx.recent_commits)} commits[/dim]"
        )

        # Phase 2: single model call
        with Live(console=console, refresh_per_second=4) as live:
            live.update(Text.from_markup("⟳ [cyan]Analysing with claude-haiku-4-5…[/cyan]"))

            import threading
            from agent.analyzer import analyze

            result_box: dict = {}
            error_box: dict = {}

            def run() -> None:
                try:
                    result_box["value"] = analyze(
                        ctx,
                        thinking_budget=thinking_budget,
                        verbose=verbose,
                    )
                except Exception as exc:
                    error_box["value"] = exc

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            while thread.is_alive():
                thread.join(timeout=0.25)
            live.update(Text(""))

        if "value" in error_box:
            console.print(f"[red]Error: {error_box['value']}[/red]")
            sys.exit(1)

        analysis = result_box["value"]
        elapsed = time.monotonic() - start

        # ── Cache the result ──────────────────────────────────────────────────
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(analysis.model_dump_json(indent=2))
        console.print(f"[dim]Analysis cached to {cache_path}[/dim]")
        console.print(f"[green]✓ Analysis complete in {elapsed:.1f}s[/green]")

    # ── Render HTML ───────────────────────────────────────────────────────────
    from output.renderer import render_html

    out_path = pathlib.Path(output) if output else pathlib.Path(f"{analysis.project_name}_report.html")
    render_html(analysis, output_path=out_path)

    console.print(f"[bold green]✓ Report written to {out_path}[/bold green]")
    _print_cost_estimate()


def _dry_run(repo_url: str) -> None:
    """Show what the fetcher would collect, then exit."""
    console.print("[bold yellow]Dry-run mode — fetcher plan:[/bold yellow]")
    slug = repo_url.rstrip("/").replace("https://github.com/", "")
    console.print(f"  Repo slug : [cyan]{slug}[/cyan]")
    console.print(f"  1. GET /repos/{slug}  — metadata")
    console.print(f"  2. GET /repos/{slug}/git/trees/HEAD?recursive=1  — full file tree")
    console.print(f"  3. GET /repos/{slug}/contents/<path>  — up to 15 key files")
    console.print(f"  4. GET /repos/{slug}/commits  — 15 recent commits")
    console.print("  5. Single claude-haiku-4-5 call → JSON output")
    console.print("[dim]Use without --dry-run to run the full analysis.[/dim]")


def _print_cost_estimate() -> None:
    """Print a rough cost estimate based on Haiku 4.5 pricing."""
    # ~10k input non-cached, ~2k cache write, ~8k thinking, ~3k output
    est = (10_000 * 0.80 + 2_000 * 1.00 + 8_000 * 0.80 + 3_000 * 4.00) / 1_000_000
    console.print(f"[dim]Estimated cost: ~${est:.3f} (claude-haiku-4-5)[/dim]")


if __name__ == "__main__":
    cli()
