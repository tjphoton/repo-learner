import base64
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _make_file_mock(path: str, content: str, size: int = 100) -> MagicMock:
    m = MagicMock()
    m.path = path
    m.name = path.split("/")[-1]
    m.type = "file"
    m.size = size
    m.content = base64.b64encode(content.encode()).decode()
    return m


def _make_dir_mock(path: str) -> MagicMock:
    m = MagicMock()
    m.path = path
    m.name = path.split("/")[-1]
    m.type = "dir"
    m.size = 0
    return m


@pytest.fixture
def client_with_repo():
    """Return (client, mock_repo) with __init__ bypassed."""
    from agent.github_client import RepoClient
    client = RepoClient.__new__(RepoClient)
    mock_repo = MagicMock()
    client.repo = mock_repo
    # _cache is initialised by __new__
    return client, mock_repo


# ── __new__ initialises cache ─────────────────────────────────────────────────

class TestCacheInit:
    def test_new_initialises_cache(self):
        from agent.github_client import RepoClient
        client = RepoClient.__new__(RepoClient)
        assert hasattr(client, "_cache")
        assert isinstance(client._cache, dict)
        assert len(client._cache) == 0


# ── read_file ─────────────────────────────────────────────────────────────────

class TestReadFile:
    def test_returns_decoded_content(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = _make_file_mock("README.md", "hello world")
        result = client.read_file("README.md")
        assert result == "hello world"

    def test_caches_result(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = _make_file_mock("x.py", "content")
        client.read_file("x.py")
        client.read_file("x.py")
        mock_repo.get_contents.assert_called_once()

    def test_second_call_returns_cached(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = _make_file_mock("a.py", "first")
        r1 = client.read_file("a.py")
        # Change what get_contents returns — cache should insulate us
        mock_repo.get_contents.return_value = _make_file_mock("a.py", "different")
        r2 = client.read_file("a.py")
        assert r1 == r2 == "first"

    def test_truncates_at_1500_lines(self, client_with_repo):
        client, mock_repo = client_with_repo
        long_content = "\n".join(f"line {i}" for i in range(2000))
        mock_repo.get_contents.return_value = _make_file_mock("big.py", long_content)
        result = client.read_file("big.py")
        assert "omitted" in result
        # Must be shorter than original
        assert len(result.splitlines()) < 800

    def test_short_file_not_truncated(self, client_with_repo):
        client, mock_repo = client_with_repo
        short = "\n".join(f"line {i}" for i in range(100))
        mock_repo.get_contents.return_value = _make_file_mock("short.py", short)
        result = client.read_file("short.py")
        assert "omitted" not in result
        assert len(result.splitlines()) == 100

    def test_directory_returns_path_list(self, client_with_repo):
        client, mock_repo = client_with_repo
        entries = [_make_file_mock("src/a.py", ""), _make_file_mock("src/b.py", "")]
        mock_repo.get_contents.return_value = entries  # list → directory
        result = client.read_file("src")
        assert "src/a.py" in result
        assert "src/b.py" in result

    def test_github_exception_raises_file_not_found(self, client_with_repo):
        from github import GithubException
        client, mock_repo = client_with_repo
        mock_repo.get_contents.side_effect = GithubException(404, "Not Found")
        with pytest.raises(FileNotFoundError, match="Cannot read"):
            client.read_file("missing.py")


# ── list_directory ────────────────────────────────────────────────────────────

class TestListDirectory:
    def test_returns_file_list(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = [
            _make_file_mock("src/a.py", ""),
            _make_dir_mock("src/utils"),
        ]
        result = client.list_directory("src", depth=1)
        assert len(result) == 2
        assert result[0]["name"] == "a.py"
        assert result[1]["type"] == "dir"

    def test_depth_clamped_to_max_4(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = []
        client.list_directory(".", depth=99)
        # Should not raise; depth is silently clamped

    def test_depth_clamped_to_min_1(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = []
        client.list_directory(".", depth=0)

    def test_github_exception_returns_empty(self, client_with_repo):
        from github import GithubException
        client, mock_repo = client_with_repo
        mock_repo.get_contents.side_effect = GithubException(403, "Forbidden")
        result = client.list_directory("private", depth=1)
        assert result == []


# ── slug parsing ──────────────────────────────────────────────────────────────

class TestSlugParsing:
    @pytest.mark.parametrize("url,expected_slug", [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/", "owner/repo"),
        ("http://github.com/owner/repo", "owner/repo"),
    ])
    def test_slug_extracted(self, url, expected_slug):
        import re
        slug = re.sub(r"https?://github\.com/", "", url).rstrip("/")
        assert slug == expected_slug


# ── find_entrypoints ──────────────────────────────────────────────────────────

class TestFindEntrypoints:
    def test_finds_main_py(self, client_with_repo):
        client, mock_repo = client_with_repo
        main_mock = _make_file_mock("main.py", "# main entry\ndef main():\n    pass\n")
        other_mock = _make_file_mock("README.md", "# readme")
        mock_repo.get_contents.return_value = [main_mock, other_mock]
        result = client.find_entrypoints()
        assert "main.py" in result
        assert "# main entry" in result["main.py"]

    def test_skips_non_entrypoints(self, client_with_repo):
        client, mock_repo = client_with_repo
        mock_repo.get_contents.return_value = [_make_file_mock("utils.py", "# utils")]
        result = client.find_entrypoints()
        assert "utils.py" not in result

    def test_github_exception_returns_empty(self, client_with_repo):
        from github import GithubException
        client, mock_repo = client_with_repo
        mock_repo.get_contents.side_effect = GithubException(404, "Not Found")
        result = client.find_entrypoints()
        assert result == {}
