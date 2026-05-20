# Codebase Learning Agent

A CLI tool that takes a remote GitHub repo URL and produces a self-contained interactive HTML learning document using Claude's extended thinking and tool use.

## Model

`claude-haiku-4-5-20251001` with extended thinking (`budget_tokens: 8000`). Do not switch models without explicit instruction.

## Project Layout

```
repo-learner/
├── main.py                    # Click CLI entry point
├── agent/
│   ├── loop.py                # Agentic loop (30-round max)
│   ├── tools.py               # 6 tool schemas + dispatch()
│   ├── github_client.py       # PyGithub wrapper, LRU-cached
│   └── models.py              # Pydantic AnalysisOutput + sub-models
├── output/
│   ├── renderer.py            # AnalysisOutput → self-contained HTML
│   └── templates/
│       └── report.html.j2     # Jinja2 base template
├── prompts/
│   └── system.md              # Cached system prompt (injected at runtime)
└── tests/
    ├── conftest.py
    ├── unit/                  # 50+ tests, fully mocked, <5s
    ├── integration/           # 15 tests, VCR cassettes, no live network
    │   └── cassettes/
    └── e2e/                   # 3 tests, real APIs, @pytest.mark.slow
```

## Commands

```bash
uv run repo-learn <REPO_URL>                  # analyse a repo
uv run repo-learn <REPO_URL> --dry-run        # print first 3 tool calls, exit
uv run repo-learn <REPO_URL> --verbose        # show tool calls + thinking tokens
uv run repo-learn <REPO_URL> --thinking-budget 12000  # override budget

uv run pytest tests/unit tests/integration    # fast tests (no live API)
uv run pytest -m slow tests/e2e              # E2E (requires API keys)
uv run pytest --cov --cov-fail-under=85      # coverage gate
uv run ruff check .                          # lint
uv run mypy agent/ output/                   # type check
```

## Key Invariants

- **Thinking blocks must be forwarded verbatim** in every subsequent assistant turn. Stripping them causes a 400 API error.
- **Prompt caching** is applied to the system prompt via `cache_control: {type: ephemeral}`. Always keep this.
- **Tool dispatch returns an envelope**: `{"ok": bool, "data": ...}` or `{"ok": false, "error": "..."}`. Never raise from dispatch; always catch and wrap.
- **HTML output is self-contained**: no `cdn.jsdelivr.net` or any external URL in the rendered file. Mermaid and Prism are inlined.
- **`AnalysisOutput.key_files` must be exactly 10 entries**, ranked 1–10 with unique ranks.
- **CI never calls real APIs**: `--vcr-record=none` is set in CI. Cassettes live in `tests/integration/cassettes/`.

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (agent + E2E) | Claude API |
| `GITHUB_TOKEN` | Recommended | Avoids GitHub rate limits (5000/hr vs 60/hr) |

## Testing Rules

- Unit tests: mock everything at the boundary (`unittest.mock`). No real HTTP.
- Integration tests: use `@pytest.mark.vcr` cassettes recorded once, replayed forever.
- E2E tests: marked `@pytest.mark.slow`, skipped if `ANTHROPIC_API_KEY` not set.
- Coverage floor: **85%** on `agent/` and `output/`. `models.py` must be 100%.
- Never use `--vcr-record=all` in CI. Only use `new_episodes` locally when adding new cassettes.

## Cost Model (claude-sonnet-4-6)

| Token type | Rate |
|---|---|
| Input | $0.80 / M |
| Cache write | $1.00 / M |
| Cache read | $0.08 / M |
| Thinking | $0.80 / M |
| Output | $4.00 / M |

Typical run: ~$0.03 (claude-haiku-4-5).

## Commit Convention

After fixing a bug or completing a feature: `git commit` with a descriptive message and sync to GitHub. Follow the global CLAUDE.md instruction.
