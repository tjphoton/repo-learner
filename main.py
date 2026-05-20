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
@click.option("--verbose", "-v", is_flag=True, help="Print tool calls and thinking token counts")
@click.option("--dry-run", is_flag=True, help="Print first 3 tool calls the agent would make, then exit")
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
            console.print("[green]✓ Cache hit — skipping agent run[/green]")
        except Exception as exc:
            console.print(f"[yellow]Cache invalid ({exc}), re-running agent[/yellow]")
            analysis = None

    # ── Run agent ─────────────────────────────────────────────────────────────
    if analysis is None:
        console.print(f"[bold]Analysing[/bold] [cyan]{repo_url}[/cyan]")
        console.print(f"[dim]Model: claude-sonnet-4-6 · thinking budget: {thinking_budget:,} tokens[/dim]")

        round_info = {"current": 0, "status": "starting"}

        def progress_callback(round_num: int, stop_reason: str) -> None:
            round_info["current"] = round_num
            round_info["status"] = stop_reason

        start = time.monotonic()

        with Live(console=console, refresh_per_second=4) as live:
            def render_spinner() -> Text:
                t = Text()
                t.append("⟳ ", style="cyan")
                t.append(f"Exploring… (round {round_info['current']}/30)", style="white")
                return t

            from agent.loop import run_agent

            import threading

            result_box: dict = {}
            error_box: dict = {}

            def run() -> None:
                try:
                    result_box["value"] = run_agent(
                        repo_url,
                        thinking_budget=thinking_budget,
                        verbose=verbose,
                        progress_callback=progress_callback,
                    )
                except Exception as exc:
                    error_box["value"] = exc

            thread = threading.Thread(target=run, daemon=True)
            thread.start()

            while thread.is_alive():
                live.update(render_spinner())
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
    _print_cost_estimate(analysis)


def _dry_run(repo_url: str) -> None:
    """Print the first 3 tool calls the agent would make, then exit."""
    console.print("[bold yellow]Dry-run mode — first 3 tool calls:[/bold yellow]")
    calls = [
        ("repo_metadata", {"repo_url": repo_url}),
        ("find_entrypoints", {}),
        ("list_directory", {"path": "", "depth": 3}),
    ]
    for i, (name, inputs) in enumerate(calls, 1):
        console.print(f"  {i}. [cyan]{name}[/cyan]({json.dumps(inputs)})")
    console.print("[dim]Use without --dry-run to run the full analysis.[/dim]")


def _print_cost_estimate(analysis: object) -> None:
    """Print a rough cost estimate based on typical token counts."""
    # Typical for a medium repo: 8k input non-cached, 40k cache reads, 8k thinking, 3k output
    est = (8_000 * 3 + 40_000 * 0.30 + 8_000 * 3 + 3_000 * 15) / 1_000_000
    console.print(f"[dim]Estimated cost: ~${est:.3f} (claude-sonnet-4-6)[/dim]")


if __name__ == "__main__":
    cli()
