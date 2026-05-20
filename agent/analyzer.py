from __future__ import annotations

import json
import pathlib
import time
from typing import Any

import anthropic

from agent.fetcher import RepoContext
from agent.models import AnalysisOutput, output_schema_json, validate_output

_MODEL = "claude-haiku-4-5-20251001"
_SYSTEM_TEMPLATE = pathlib.Path(__file__).parent.parent / "prompts" / "system.md"


def _build_system() -> list[Any]:
    schema = output_schema_json()
    text = _SYSTEM_TEMPLATE.read_text().replace("SCHEMA_PLACEHOLDER", schema)
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _build_user_message(ctx: RepoContext) -> str:
    parts: list[str] = []

    parts.append(f"# Repository: {ctx.owner}/{ctx.name}")
    parts.append(f"URL: {ctx.url}")
    parts.append(f"Description: {ctx.description}")
    parts.append(
        f"Primary language: {ctx.language} | Stars: {ctx.stars:,} | "
        f"Default branch: {ctx.default_branch}"
    )
    if ctx.topics:
        parts.append(f"Topics: {', '.join(ctx.topics)}")

    parts.append("\n## File Tree")
    parts.append("\n".join(ctx.file_tree))
    if len(ctx.file_tree) == 600:
        parts.append("... [tree truncated at 600 entries]")

    if ctx.recent_commits:
        parts.append("\n## Recent Commits")
        parts.append("\n".join(ctx.recent_commits))

    for fc in ctx.key_files:
        suffix = " (truncated)" if fc.truncated else ""
        parts.append(f"\n## {fc.path}{suffix}")
        ext = fc.path.rsplit(".", 1)[-1] if "." in fc.path else ""
        parts.append(f"```{ext}\n{fc.content}\n```")

    parts.append("\n---\nAnalyse the repository content above and produce the JSON output now.")
    return "\n".join(parts)


def analyze(
    ctx: RepoContext,
    thinking_budget: int = 8000,
    verbose: bool = False,
) -> AnalysisOutput:
    """Make a single API call to analyse pre-fetched repo content."""
    client = anthropic.Anthropic()
    system = _build_system()
    user_content = _build_user_message(ctx)

    if verbose:
        import sys
        print(
            f"[analyzer] context ~{len(user_content) // 4:,} tokens",
            file=sys.stderr,
        )

    for attempt in range(3):
        try:
            response = client.messages.create(  # type: ignore[call-overload]
                model=_MODEL,
                max_tokens=thinking_budget + 8000,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except anthropic.RateLimitError:
            if attempt == 2:
                raise
            wait = 60 * (attempt + 1)
            import sys
            print(
                f"[rate limit] sleeping {wait}s before retry {attempt + 2}/3…",
                file=sys.stderr,
            )
            time.sleep(wait)

    if verbose:
        import sys
        thinking_tokens = sum(
            len(getattr(b, "thinking", "") or "") // 4
            for b in response.content
            if getattr(b, "type", "") == "thinking"
        )
        print(
            f"[analyzer] stop={response.stop_reason} think_tokens≈{thinking_tokens:,}",
            file=sys.stderr,
        )

    for block in reversed(response.content):
        if getattr(block, "type", "") == "text":
            text = _strip_fences(block.text)  # type: ignore[union-attr]
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                import sys
                preview = text[:500].replace("\n", "\\n")
                print(f"[analyzer] JSON parse error: {exc}", file=sys.stderr)
                print(f"[analyzer] Response preview: {preview}", file=sys.stderr)
                raise ValueError(f"Model output is not valid JSON: {exc}") from exc
            return validate_output(raw)

    raise ValueError("Model returned no text block")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may have added despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        # drop first line (```json or ```) and last ``` line
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    return text
