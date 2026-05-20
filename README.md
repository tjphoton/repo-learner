# repo-learner

Turn any GitHub repository into an interactive HTML learning document in one command.

Powered by **claude-haiku-4-5** with extended thinking. The tool pre-fetches the repo content (file tree, key files, commits) without any model involvement, then makes a **single API call** to produce a self-contained HTML report covering six sections: project overview, directory structure, key files, data flow, innovation analysis, and a vibe-coding rebuild guide with copy-able Claude Code prompts.

---

## Quick start

```bash
# 1. Set required env vars
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."          # recommended — avoids 60 req/hr rate limit

# 2. Install
pip install uv                         # if you don't have it
git clone https://github.com/tjphoton/repo-learner
cd repo-learner
uv sync

# 3. Run
uv run repo-learn https://github.com/owner/repo
# → writes <project>_report.html
```

Open the HTML file in any browser — no server needed.

---

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Get one at [console.anthropic.com](https://console.anthropic.com) |
| `GITHUB_TOKEN` | Recommended | 5 000 req/hr vs 60 req/hr unauthenticated. Create at GitHub → Settings → Developer settings → Personal access tokens |

You can also put these in a `.env` file (see `.env.example`).

---

## CLI reference

```
uv run repo-learn [OPTIONS] REPO_URL
```

| Option | Default | Description |
|---|---|---|
| `--output`, `-o` | `<name>_report.html` | Output HTML path |
| `--thinking-budget` | `8000` | Extended thinking token budget (higher = deeper analysis, more cost) |
| `--cache-dir` | `.agent_cache` | Directory to cache analysis JSON. Re-run with the same URL to skip the fetch+analysis and re-render only. |
| `--verbose`, `-v` | off | Print context size and thinking token count to stderr |
| `--dry-run` | off | Print the fetch plan (no API calls, free) |

### Examples

```bash
# Default run
uv run repo-learn https://github.com/fastapi/fastapi

# Save to a specific path
uv run repo-learn https://github.com/fastapi/fastapi -o reports/fastapi.html

# Deeper analysis (costs a little more)
uv run repo-learn https://github.com/fastapi/fastapi --thinking-budget 15000

# See what the analyzer receives
uv run repo-learn https://github.com/fastapi/fastapi --verbose

# Re-render from cache without calling the API again
uv run repo-learn https://github.com/fastapi/fastapi
# (second run hits cache automatically)

# Preview fetch plan without spending any tokens
uv run repo-learn https://github.com/fastapi/fastapi --dry-run
```

---

## How it works

```
REPO_URL
  │
  ▼
Phase 1 — Fetch (PyGithub, no model)
  │  • repo metadata      — description, language, stars
  │  • full file tree     — one recursive git tree API call
  │  • key file contents  — up to 15 files (README, entry points, config, source)
  │  • recent commits     — last 15 commit messages
  │
  ▼
Assembled context (~10k tokens)
  │
  ▼
Phase 2 — Analyse (claude-haiku-4-5, single API call)
  │  extended thinking → reasons across all provided content
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

The system prompt uses **prompt caching** (`cache_control: ephemeral`) to avoid re-charging input tokens on re-renders. **Extended thinking** lets the model reason across multiple file relationships before drawing conclusions.

---

## File selection heuristic

The fetcher always reads files in this priority order (up to 15 total):

1. README (any format)
2. Top-level entry points (`main.py`, `index.ts`, `Dockerfile`, …)
3. Top-level config / manifests (`pyproject.toml`, `package.json`, `go.mod`, …)
4. One CI workflow file (`.github/workflows/`)
5. Other top-level source files
6. Files one level deep in `src/`, `lib/`, `core/`, `app/`, etc.

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
| Input (non-cached) | $0.80 / M | ~10k | $0.008 |
| Cache write | $1.00 / M | ~2k | $0.002 |
| Cache read | $0.08 / M | ~2k | $0.000 |
| Thinking | $0.80 / M | ~8k | $0.006 |
| Output | $4.00 / M | ~3k | $0.012 |
| **Total** | | | **~$0.03** |

Haiku 4.5 + single API call = ~10× cheaper than the old Sonnet agentic loop.

---

## Development

```bash
uv sync --extra test --extra dev

# Unit + integration tests (no API keys needed)
uv run pytest tests/unit tests/integration -q

# With coverage (gate at 85%)
uv run pytest tests/unit tests/integration --cov --cov-fail-under=85

# E2E tests (requires API keys, ~$0.05 total)
uv run pytest -m slow tests/e2e/ -v

# Lint + type check
uv run ruff check .
uv run mypy agent/ output/ main.py --ignore-missing-imports
```

### Test structure

```
tests/
├── unit/           # 100 tests, fully mocked, <5s total
├── integration/    # pipeline tests, mocked GitHub + Anthropic
└── e2e/            # real APIs, @pytest.mark.slow
```

---

## Project structure

```
repo-learner/
├── main.py                    # Click CLI
├── agent/
│   ├── fetcher.py             # GitHub pre-fetch (no model)
│   ├── analyzer.py            # Single API call → AnalysisOutput
│   └── models.py              # Pydantic output schema
├── output/
│   ├── renderer.py            # JSON → HTML
│   └── templates/
│       └── report.html.j2     # Jinja2 template
└── prompts/
    └── system.md              # System prompt (injected with schema at runtime)
```

---

## License

MIT
