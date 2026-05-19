"""
Integration tests for agent/github_client.py.

These tests exercise the RepoClient interface using a fully mocked PyGithub
layer — no real network calls. They verify the client's behaviour when the
GitHub API returns realistic response shapes.
"""
import base64
import pytest
from unittest.mock import MagicMock, patch

from github import GithubException


def _file(path: str, content: str = "# content", size: int = 50) -> MagicMock:
    m = MagicMock()
    m.path = path
    m.name = path.split("/")[-1]
    m.type = "file"
    m.size = size
    m.content = base64.b64encode(content.encode()).decode()
    return m


def _dir(path: str) -> MagicMock:
    m = MagicMock()
    m.path = path
    m.name = path.split("/")[-1]
    m.type = "dir"
    m.size = 0
    return m


@pytest.fixture
def client():
    from agent.github_client import RepoClient
    c = RepoClient.__new__(RepoClient)
    c.repo = MagicMock()
    c.repo.full_name = "owner/repo"
    return c


# ── repo_metadata ─────────────────────────────────────────────────────────────

class TestRepoMetadata:
    def test_returns_expected_keys(self, client):
        client.repo.name = "my-repo"
        client.repo.full_name = "owner/my-repo"
        client.repo.description = "A test repo"
        client.repo.language = "Python"
        client.repo.get_topics.return_value = ["ai", "python"]
        client.repo.stargazers_count = 42
        client.repo.forks_count = 5
        client.repo.license = MagicMock(name="MIT License")
        client.repo.default_branch = "main"
        client.repo.created_at = None
        client.repo.get_contents.return_value = [_file("README.md")]

        meta = client.repo_metadata()
        assert meta["name"] == "my-repo"
        assert meta["language"] == "Python"
        assert meta["stars"] == 42
        assert "ai" in meta["topics"]
        assert "README.md" in str(meta["root_entries"])

    def test_handles_no_license(self, client):
        client.repo.name = "r"
        client.repo.full_name = "o/r"
        client.repo.description = ""
        client.repo.language = ""
        client.repo.get_topics.return_value = []
        client.repo.stargazers_count = 0
        client.repo.forks_count = 0
        client.repo.license = None
        client.repo.default_branch = "main"
        client.repo.created_at = None
        client.repo.get_contents.return_value = []
        meta = client.repo_metadata()
        assert meta["license"] is None

    def test_handles_root_contents_exception(self, client):
        client.repo.name = "r"
        client.repo.full_name = "o/r"
        client.repo.description = ""
        client.repo.language = "Go"
        client.repo.get_topics.return_value = []
        client.repo.stargazers_count = 0
        client.repo.forks_count = 0
        client.repo.license = None
        client.repo.default_branch = "main"
        client.repo.created_at = None
        client.repo.get_contents.side_effect = GithubException(403, "Forbidden")
        meta = client.repo_metadata()
        assert meta["root_entries"] == []


# ── get_commits ───────────────────────────────────────────────────────────────

class TestGetCommits:
    def _make_commit(self, sha: str, message: str, files=None):
        c = MagicMock()
        c.sha = sha
        c.commit.message = message
        author = MagicMock()
        author.name = "Alice"
        from datetime import datetime
        author.date = datetime(2024, 1, 1)
        c.commit.author = author
        file_mocks = []
        for f in (files or ["src/main.py"]):
            fm = MagicMock()
            fm.filename = f
            file_mocks.append(fm)
        c.files = file_mocks
        return c

    def test_returns_correct_count(self, client):
        commits = [self._make_commit(f"sha{i:040d}", f"commit {i}") for i in range(15)]
        client.repo.get_commits.return_value = commits
        result = client.get_commits(n=10)
        assert len(result) == 10

    def test_commit_structure(self, client):
        client.repo.get_commits.return_value = [
            self._make_commit("abc123def456abc123def456abc123def456abc1", "fix: bug", ["main.py"])
        ]
        result = client.get_commits(n=1)
        assert result[0]["sha"] == "abc123de"  # first 8 chars
        assert result[0]["message"] == "fix: bug"
        assert "main.py" in result[0]["files_changed"]

    def test_n_clamped_to_30(self, client):
        commits = [self._make_commit(f"s{'0'*39}", "m") for _ in range(50)]
        client.repo.get_commits.return_value = commits
        result = client.get_commits(n=100)
        assert len(result) <= 30

    def test_multiline_message_truncated(self, client):
        client.repo.get_commits.return_value = [
            self._make_commit("a" * 40, "first line\nsecond line\nthird line")
        ]
        result = client.get_commits(n=1)
        assert "\n" not in result[0]["message"]
        assert result[0]["message"] == "first line"


# ── search_code (cached files fallback) ──────────────────────────────────────

class TestSearchCodeFallback:
    def test_searches_cached_files(self, client):
        # Pre-populate cache to trigger the fallback path
        client._cache["src/main.py"] = "import fastapi\nfrom fastapi import FastAPI\napp = FastAPI()"
        client.repo.get_contents.side_effect = GithubException(403, "Forbidden")

        # Patch out the GitHub search API call to force fallback
        with patch("agent.github_client.Github"):
            results = client.search_code("import fastapi", max_results=5)

        assert any(r["file"] == "src/main.py" for r in results)

    def test_max_results_respected(self, client):
        long_content = "\n".join(["import foo"] * 100)
        client._cache["big.py"] = long_content
        client.repo.get_contents.side_effect = GithubException(403, "Forbidden")

        with patch("agent.github_client.Github"):
            results = client.search_code("import foo", max_results=5)

        assert len(results) <= 5
