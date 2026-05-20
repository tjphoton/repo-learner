# Codebase Learning Agent

A CLI tool that takes a remote GitHub repo URL and produces a self-contained interactive HTML learning document using Claude's extended thinking.

## Architecture

Two-phase, no agentic loop:
1. **Fetch** (`agent/fetcher.py`) — PyGithub collects metadata, file tree, key file contents, and commits. No model involved.
2. **Analyze** (`agent/analyzer.py`) — One API call to Haiku with all fetched content. Returns `AnalysisOutput` JSON.

## Model

`claude-haiku-4-5-20251001` with extended thinking (`budget_tokens: 8000`). Do not switch models without explicit instruction.

## Project Layout

```
repo-learner/
├── main.py                    # Click CLI entry point
├── agent/
│   ├── fetcher.py             # GitHub pre-fetch (no model)
│   ├── analyzer.py            # Single Haiku API call → AnalysisOutput
│   └── models.py              # Pydantic AnalysisOutput + sub-models
├── output/
│   ├── renderer.py            # AnalysisOutput → self-contained HTML
│   └── templates/
│       └── report.html.j2     # Jinja2 base template
├── prompts/
│   └── system.md              # Cached system prompt (injected at runtime)
└── tests/
    ├── conftest.py
    ├── unit/                  # 100 tests, fully mocked, <5s
    ├── integration/           # pipeline tests, no live network
    └── e2e/                   # real APIs, @pytest.mark.slow
```

## Commands

```bash
uv run repo-learn <REPO_URL>                  # analyse a repo
uv run repo-learn <REPO_URL> --dry-run        # show fetch plan, exit
uv run repo-learn <REPO_URL> --verbose        # show context size + thinking tokens
uv run repo-learn <REPO_URL> --thinking-budget 12000  # override budget

uv run pytest tests/unit tests/integration    # fast tests (no live API)
uv run pytest -m slow tests/e2e              # E2E (requires API keys)
uv run pytest --cov --cov-fail-under=85      # coverage gate
uv run ruff check .                          # lint
uv run mypy agent/ output/                   # type check
```

## Key Invariants

- **Single API call**: `analyzer.py` makes exactly one `messages.create` call per run. No loop.
- **Prompt caching** is applied to the system prompt via `cache_control: {type: ephemeral}`. Always keep this.
- **HTML output is self-contained**: no `cdn.jsdelivr.net` or any external URL in the rendered file. Mermaid and Prism are inlined.
- **`AnalysisOutput.key_files` must be exactly 10 entries**, ranked 1–10 with unique ranks.
- **CI never calls real APIs**: all unit and integration tests mock the Anthropic and GitHub clients.
- **Fetcher is deterministic**: `fetcher.py` always selects files by the same priority order. The model never decides what to read.

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API |
| `GITHUB_TOKEN` | Recommended | Avoids GitHub rate limits (5000/hr vs 60/hr) |

## Testing Rules

- Unit tests: mock everything at the boundary (`unittest.mock`). No real HTTP.
- Integration tests: mock both GitHub and Anthropic clients end-to-end.
- E2E tests: marked `@pytest.mark.slow`, skipped if `ANTHROPIC_API_KEY` not set.
- Coverage floor: **85%** on `agent/` and `output/`. `models.py` must be 100%.

## Cost Model (claude-haiku-4-5)

| Token type | Rate |
|---|---|
| Input | $0.80 / M |
| Cache write | $1.00 / M |
| Cache read | $0.08 / M |
| Thinking | $0.80 / M |
| Output | $4.00 / M |

Typical run: ~$0.03. One API call, ~10k input tokens.

## Commit Convention

After fixing a bug or completing a feature: `git commit` with a descriptive message and sync to GitHub. Follow the global CLAUDE.md instruction.
