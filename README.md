# repo-learner

Turn any GitHub repository into an interactive HTML learning document in one command.

Powered by **claude-sonnet-4-6** with extended thinking and agentic tool use. The agent explores the repo autonomously (up to 30 rounds of tool calls), then produces a self-contained HTML report covering six sections: project overview, directory structure, key files, data flow, innovation analysis, and a vibe-coding rebuild guide with copy-able Claude Code prompts.

---

## Quick start

```bash
# 1. Set required env vars
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."          # recommended — avoids 60 req/hr rate limit

# 2. Install
pip install uv                         # if you don't have it
git clone https://github.com/your-org/repo-learner
cd repo-learner
uv sync

# 3. Run
uv run repo-learn https://github.com/steipete/summarize
# → writes summarize_report.html
```

Open the HTML file in any browser — no server needed.

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Get one at [console.anthropic.com](https://console.anthropic.com) |
| `GITHUB_TOKEN` | Recommended | 5 000 req/hr vs 60 req/hr unauthenticated. Create at GitHub → Settings → Developer settings → Personal access tokens |

---

## CLI reference

```
uv run repo-learn [OPTIONS] REPO_URL
```

| Option | Default | Description |
|---|---|---|
| `--output`, `-o` | `<name>_report.html` | Output HTML path |
| `--thinking-budget` | `8000` | Extended thinking token budget (higher = deeper analysis, more cost) |
| `--cache-dir` | `.agent_cache` | Directory to cache analysis JSON. Re-run with the same URL to skip the agent and re-render only. |
| `--verbose`, `-v` | off | Print each tool call and thinking token count to stderr |
| `--dry-run` | off | Print the first 3 tool calls the agent would make, then exit (free) |

### Examples

```bash
# Default run
uv run repo-learn https://github.com/fastapi/fastapi

# Save to a specific path
uv run repo-learn https://github.com/fastapi/fastapi -o reports/fastapi.html

# Deeper analysis (costs a little more)
uv run repo-learn https://github.com/fastapi/fastapi --thinking-budget 15000

# See what the agent is doing
uv run repo-learn https://github.com/fastapi/fastapi --verbose

# Re-render from cache without calling the API again
uv run repo-learn https://github.com/fastapi/fastapi
# (second run hits cache automatically)

# Preview tool calls without spending any tokens
uv run repo-learn https://github.com/fastapi/fastapi --dry-run
```

---

## How it works

```
REPO_URL
  │
  ▼
Agent loop (claude-sonnet-4-6, extended thinking)
  │  up to 30 rounds of tool calls:
  │  • repo_metadata      — description, language, stars, root layout
  │  • find_entrypoints   — main.py, index.ts, Dockerfile, etc.
  │  • list_directory     — recursive tree up to depth 4
  │  • read_file          — file contents (auto-truncated at 1500 lines)
  │  • search_code        — regex search across the repo
  │  • get_commits        — recent commit history + churn signals
  │
  ▼
AnalysisOutput JSON (cached to .agent_cache/)
  │
  ▼
Jinja2 renderer
  │
  ▼
self-contained HTML report
```

The agent uses **prompt caching** on the system prompt (saves ~70% of per-round input token cost) and **extended thinking** to reason across multiple file reads before drawing conclusions — catching things a single-prompt approach misses.

---

## Output sections

| # | Section | What it contains |
|---|---|---|
| 1 | **Project Overview** | Purpose, tech stack badges, Mermaid architecture diagram |
| 2 | **Directory Structure** | Annotated tree — what each top-level folder does |
| 3 | **Key Files** | Top 10 files ranked by importance, expandable with syntax-highlighted excerpts |
| 4 | **Data Flow** | Mermaid sequence diagram tracing a request end-to-end, step-by-step breakdown |
| 5 | **Innovation** | Side-by-side table: conventional approach vs this project, and why it matters |
| 6 | **Rebuild Guide** | 4–6 phased build plan with copy-able Claude Code prompts for each phase |

---

## Cost

Typical run on a medium-size repo (~200 files):

| Token type | Rate | Typical usage | Cost |
|---|---|---|---|
| Input (non-cached) | $3.00 / M | ~8k | $0.024 |
| Cache write | $3.75 / M | ~2k | $0.008 |
| Cache read | $0.30 / M | ~40k | $0.012 |
| Thinking | $3.00 / M | ~8k | $0.024 |
| Output | $15.00 / M | ~3k | $0.045 |
| **Total** | | | **~$0.11** |

Large repos (500+ files) automatically use a two-phase strategy: a cheap Haiku pass maps the structure, then Sonnet does the deep analysis.

---

## Development

```bash
uv sync --extra test --extra dev

# Unit + integration tests (no API keys needed)
uv run pytest tests/unit tests/integration -q

# With coverage (gate at 85%)
uv run pytest tests/unit tests/integration --cov=agent --cov=output --cov-fail-under=85

# E2E tests (requires API keys, ~$0.30 total)
uv run pytest -m slow tests/e2e/ -v

# Lint + type check
uv run ruff check .
uv run mypy agent/ output/ main.py --ignore-missing-imports
```

### Test structure

```
tests/
├── unit/           # 50+ tests, fully mocked, <5s total
├── integration/    # 15 tests, mocked Claude API, no live network
└── e2e/            # 3 tests, real APIs, @pytest.mark.slow
```

Key invariants verified by the integration tests:
- Model string is always `claude-sonnet-4-6`
- Thinking blocks are forwarded verbatim in every subsequent turn
- System prompt has `cache_control: ephemeral`
- Parallel tool calls are all dispatched
- RuntimeError raised after exactly 30 rounds without convergence

---

## Project structure

```
repo-learner/
├── main.py                    # Click CLI
├── agent/
│   ├── loop.py                # Agentic loop
│   ├── tools.py               # Tool schemas + dispatch
│   ├── github_client.py       # GitHub API wrapper
│   └── models.py              # Pydantic output schema
├── output/
│   ├── renderer.py            # JSON → HTML
│   └── templates/
│       └── report.html.j2     # Jinja2 template
├── prompts/
│   └── system.md              # System prompt (injected with schema at runtime)
└── tests/
```

---

## License

MIT
