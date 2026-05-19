from __future__ import annotations

import json
import pathlib
from typing import Any

import anthropic

from agent.github_client import RepoClient
from agent.models import AnalysisOutput, output_schema_json, validate_output
from agent.tools import TOOLS, dispatch_tool

_SYSTEM_TEMPLATE = pathlib.Path(__file__).parent.parent / "prompts" / "system.md"
_MODEL = "claude-sonnet-4-6"
_MAX_ROUNDS = 30


def _build_system_prompt() -> str:
    template = _SYSTEM_TEMPLATE.read_text()
    schema = output_schema_json()
    return template.replace("SCHEMA_PLACEHOLDER", schema)


def run_agent(
    repo_url: str,
    thinking_budget: int = 8000,
    verbose: bool = False,
    progress_callback: Any = None,
) -> AnalysisOutput:
    """Run the agentic analysis loop and return a validated AnalysisOutput.

    Args:
        repo_url: Full GitHub URL to analyse.
        thinking_budget: Extended thinking token budget per API call.
        verbose: If True, print tool calls and thinking token counts to stderr.
        progress_callback: Optional callable(round_num, stop_reason) for progress UI.

    Raises:
        RuntimeError: If the agent does not converge within _MAX_ROUNDS rounds.
        ValueError: If the final JSON does not match AnalysisOutput schema.
    """
    client = anthropic.Anthropic()
    repo_client = RepoClient(repo_url)
    system_prompt = _build_system_prompt()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Analyse this repository: {repo_url}"}
    ]

    for round_num in range(1, _MAX_ROUNDS + 1):
        if progress_callback:
            progress_callback(round_num, "thinking")

        response = client.messages.create(
            model=_MODEL,
            max_tokens=16000,
            thinking={"type": "enabled", "budget_tokens": thinking_budget},
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        if verbose:
            import sys
            thinking_tokens = sum(
                getattr(b, "thinking", None) and len(getattr(b, "thinking", "")) // 4
                for b in response.content
                if getattr(b, "type", "") == "thinking"
            )
            tool_names = [
                b.name for b in response.content if getattr(b, "type", "") == "tool_use"
            ]
            print(
                f"[round {round_num}] stop={response.stop_reason} "
                f"tools={tool_names} think_tokens≈{thinking_tokens}",
                file=sys.stderr,
            )

        # Append assistant turn verbatim — thinking blocks MUST be preserved
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extract the last text block as the final JSON output
            for block in reversed(response.content):
                if getattr(block, "type", "") == "text":
                    raw = json.loads(block.text)
                    return validate_output(raw)
            raise ValueError("Agent returned end_turn with no text block")

        if response.stop_reason != "tool_use":
            raise ValueError(f"Unexpected stop_reason: {response.stop_reason}")

        # Dispatch every tool_use block (there may be multiple)
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            result = dispatch_tool(block.name, block.input, repo_client)
            if verbose:
                import sys
                ok = result.get("ok", False)
                print(
                    f"  → {block.name}({list(block.input)}) → ok={ok}",
                    file=sys.stderr,
                )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

        if progress_callback:
            progress_callback(round_num, response.stop_reason)

    raise RuntimeError(
        f"Agent did not converge within {_MAX_ROUNDS} rounds. "
        "Try increasing --thinking-budget or check the repo URL."
    )
