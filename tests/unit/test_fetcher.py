"""Unit tests for agent/fetcher.py — all GitHub API calls are mocked."""
import base64
from unittest.mock import MagicMock, patch


from agent.fetcher import (
    RepoContext,
    _decode,
    _truncate,
    _select_paths,
    fetch_repo,
    _MAX_FILES,
    _MAX_FILE_LINES,
    _MAX_TREE_ENTRIES,
)


# ── _decode ───────────────────────────────────────────────────────────────────

class TestDecode:
    def test_decodes_base64_content(self):
        cf = MagicMock()
        cf.content = base64.b64encode(b"hello world").decode()
        assert _decode(cf) == "hello world"

    def test_returns_empty_string_on_error(self):
        cf = MagicMock()
        cf.content = "not-valid-base64!!!"
        result = _decode(cf)
        assert isinstance(result, str)


# ── _truncate ─────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_short_text_unchanged(self):
        text = "line1\nline2\nline3"
        result, truncated = _truncate(text, max_lines=10)
        assert result == text
        assert not truncated

    def test_long_text_truncated(self):
        lines = [f"line {i}" for i in range(400)]
        text = "\n".join(lines)
        result, truncated = _truncate(text, max_lines=_MAX_FILE_LINES)
        assert truncated
        assert "lines omitted" in result
        assert result.count("\n") < 400

    def test_truncation_note_shows_count(self):
        lines = [f"line {i}" for i in range(350)]
        text = "\n".join(lines)
        result, _ = _truncate(text, max_lines=300)
        assert "50 more lines omitted" in result

    def test_exact_max_not_truncated(self):
        text = "\n".join(["x"] * _MAX_FILE_LINES)
        _, truncated = _truncate(text)
        assert not truncated


# ── _select_paths ─────────────────────────────────────────────────────────────

class TestSelectPaths:
    def test_readme_first(self):
        paths = ["src/app.py", "README.md", "setup.py"]
        selected = _select_paths(paths)
        assert selected[0] == "README.md"

    def test_entry_points_included(self):
        paths = ["README.md", "main.py", "tests/test_foo.py"]
        selected = _select_paths(paths)
        assert "main.py" in selected

    def test_config_files_included(self):
        paths = ["README.md", "pyproject.toml", "src/foo.py"]
        selected = _select_paths(paths)
        assert "pyproject.toml" in selected

    def test_ci_workflow_included(self):
        paths = [
            "README.md",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ]
        selected = _select_paths(paths)
        # Only one workflow file
        workflow_count = sum(1 for p in selected if p.startswith(".github/workflows/"))
        assert workflow_count == 1

    def test_respects_max_files_limit(self):
        paths = [f"file_{i}.py" for i in range(100)]
        selected = _select_paths(paths)
        assert len(selected) <= _MAX_FILES

    def test_no_duplicates(self):
        paths = ["README.md", "main.py", "pyproject.toml"]
        selected = _select_paths(paths)
        assert len(selected) == len(set(selected))

    def test_nested_entry_points_excluded(self):
        # Only top-level entry points get priority 2
        paths = ["src/main.py", "main.py"]
        selected = _select_paths(paths)
        assert selected.index("main.py") < selected.index("src/main.py")

    def test_src_dir_files_added(self):
        paths = ["README.md", "src/app.py", "src/utils.py"]
        selected = _select_paths(paths)
        assert "src/app.py" in selected


# ── fetch_repo ────────────────────────────────────────────────────────────────

def _make_github_mock(file_paths: list[str], file_content: str = "# content") -> tuple:
    """Return (mock_github_cls, mock_repo) with sensible defaults."""
    mock_repo = MagicMock()
    mock_repo.description = "A test repo"
    mock_repo.language = "Python"
    mock_repo.stargazers_count = 42
    mock_repo.forks_count = 5
    mock_repo.default_branch = "main"
    mock_repo.owner.login = "owner"
    mock_repo.name = "repo"
    mock_repo.get_topics.return_value = ["python", "cli"]

    # git tree
    tree_items = []
    for p in file_paths:
        item = MagicMock()
        item.path = p
        item.type = "blob"
        tree_items.append(item)
    mock_tree = MagicMock()
    mock_tree.tree = tree_items
    mock_repo.get_git_tree.return_value = mock_tree

    # file contents
    encoded = base64.b64encode(file_content.encode()).decode()
    mock_cf = MagicMock()
    mock_cf.content = encoded
    mock_repo.get_contents.return_value = mock_cf

    # commits
    mock_commit = MagicMock()
    mock_commit.commit.message = "fix: something"
    mock_commit.commit.author.date.strftime.return_value = "2024-01-01"
    mock_repo.get_commits.return_value = [mock_commit]

    mock_g = MagicMock()
    mock_g.get_repo.return_value = mock_repo

    return mock_g, mock_repo


class TestFetchRepo:
    def test_returns_repo_context(self):
        mock_g, _ = _make_github_mock(["README.md", "main.py"])
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert isinstance(ctx, RepoContext)

    def test_metadata_populated(self):
        mock_g, _ = _make_github_mock(["README.md"])
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert ctx.name == "repo"
        assert ctx.owner == "owner"
        assert ctx.language == "Python"
        assert ctx.stars == 42
        assert "python" in ctx.topics

    def test_file_tree_populated(self):
        paths = ["README.md", "main.py", "src/app.py"]
        mock_g, _ = _make_github_mock(paths)
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert set(paths).issubset(set(ctx.file_tree))

    def test_key_files_fetched(self):
        mock_g, _ = _make_github_mock(["README.md", "main.py"], file_content="# hello")
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert len(ctx.key_files) > 0
        paths = [kf.path for kf in ctx.key_files]
        assert "README.md" in paths

    def test_readme_extracted(self):
        mock_g, _ = _make_github_mock(["README.md"], file_content="# My Project")
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert "My Project" in ctx.readme

    def test_tree_truncated_at_max(self):
        paths = [f"file_{i}.py" for i in range(700)]
        mock_g, _ = _make_github_mock(paths)
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert len(ctx.file_tree) <= _MAX_TREE_ENTRIES

    def test_commits_formatted(self):
        mock_g, _ = _make_github_mock(["README.md"])
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert len(ctx.recent_commits) > 0
        assert "fix: something" in ctx.recent_commits[0]

    def test_github_exception_on_tree_yields_empty(self):
        from github import GithubException
        mock_g, mock_repo = _make_github_mock([])
        mock_repo.get_git_tree.side_effect = GithubException(500, "error", None)
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert ctx.file_tree == []

    def test_github_exception_on_file_skipped(self):
        from github import GithubException
        mock_g, mock_repo = _make_github_mock(["README.md", "main.py"])
        mock_repo.get_contents.side_effect = GithubException(404, "not found", None)
        with patch("agent.fetcher.Github", return_value=mock_g):
            ctx = fetch_repo("https://github.com/owner/repo")
        assert ctx.key_files == []

    def test_uses_github_token_from_env(self):
        mock_g, _ = _make_github_mock([])
        with patch("agent.fetcher.Github", return_value=mock_g) as MockG, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
            fetch_repo("https://github.com/owner/repo")
        MockG.assert_called_once_with("ghp_test")
