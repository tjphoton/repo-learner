import pytest
from unittest.mock import MagicMock, call
from agent.tools import dispatch_tool, TOOLS


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_client():
    c = MagicMock()
    c.repo_metadata.return_value = {"name": "test-repo", "language": "Python"}
    c.read_file.return_value = "# hello world"
    c.list_directory.return_value = [{"name": "src", "type": "dir", "path": "src", "size": 0}]
    c.search_code.return_value = [{"file": "main.py", "line": 1, "match": "import foo"}]
    c.get_commits.return_value = [{"sha": "abc123", "message": "init commit"}]
    c.find_entrypoints.return_value = {"main.py": "# entry point"}
    return c


# ── Routing ───────────────────────────────────────────────────────────────────

class TestDispatchRouting:
    def test_repo_metadata(self, mock_client):
        result = dispatch_tool("repo_metadata", {"repo_url": "https://github.com/x/y"}, mock_client)
        assert result["ok"] is True
        mock_client.repo_metadata.assert_called_once()

    def test_list_directory_defaults(self, mock_client):
        result = dispatch_tool("list_directory", {"path": "src"}, mock_client)
        assert result["ok"] is True
        mock_client.list_directory.assert_called_once_with("src", 2)

    def test_list_directory_custom_depth(self, mock_client):
        dispatch_tool("list_directory", {"path": "", "depth": 3}, mock_client)
        mock_client.list_directory.assert_called_once_with("", 3)

    def test_read_file(self, mock_client):
        result = dispatch_tool("read_file", {"path": "README.md"}, mock_client)
        assert result["ok"] is True
        assert result["data"] == "# hello world"
        mock_client.read_file.assert_called_once_with("README.md")

    def test_search_code_defaults(self, mock_client):
        dispatch_tool("search_code", {"pattern": "import"}, mock_client)
        mock_client.search_code.assert_called_once_with("import", "*", 20)

    def test_search_code_custom_params(self, mock_client):
        dispatch_tool("search_code", {"pattern": "def", "file_glob": "*.py", "max_results": 5}, mock_client)
        mock_client.search_code.assert_called_once_with("def", "*.py", 5)

    def test_get_commits_default(self, mock_client):
        dispatch_tool("get_commits", {}, mock_client)
        mock_client.get_commits.assert_called_once_with(10)

    def test_get_commits_custom_n(self, mock_client):
        dispatch_tool("get_commits", {"n": 20}, mock_client)
        mock_client.get_commits.assert_called_once_with(20)

    def test_find_entrypoints(self, mock_client):
        result = dispatch_tool("find_entrypoints", {}, mock_client)
        assert result["ok"] is True
        mock_client.find_entrypoints.assert_called_once()


# ── Error handling ────────────────────────────────────────────────────────────

class TestDispatchErrors:
    def test_unknown_tool_returns_error(self, mock_client):
        result = dispatch_tool("fly_to_moon", {}, mock_client)
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]
        assert "fly_to_moon" in result["error"]

    def test_unknown_tool_lists_valid_names(self, mock_client):
        result = dispatch_tool("bad_name", {}, mock_client)
        for name in ("repo_metadata", "read_file", "search_code"):
            assert name in result["error"]

    def test_exception_wrapped_in_envelope(self, mock_client):
        mock_client.read_file.side_effect = FileNotFoundError("File not found: secret.py")
        result = dispatch_tool("read_file", {"path": "secret.py"}, mock_client)
        assert result["ok"] is False
        assert "secret.py" in result["error"]

    def test_exception_does_not_propagate(self, mock_client):
        mock_client.repo_metadata.side_effect = RuntimeError("network timeout")
        result = dispatch_tool("repo_metadata", {"repo_url": "x"}, mock_client)
        assert result["ok"] is False
        assert "network timeout" in result["error"]

    def test_never_raises(self, mock_client):
        """dispatch_tool must not raise, ever."""
        mock_client.get_commits.side_effect = Exception("anything")
        try:
            dispatch_tool("get_commits", {"n": 5}, mock_client)
        except Exception as exc:
            pytest.fail(f"dispatch_tool raised unexpectedly: {exc}")


# ── Tool schema validation ────────────────────────────────────────────────────

class TestToolSchemas:
    def test_six_tools_defined(self):
        assert len(TOOLS) == 6

    def test_all_tools_have_name(self):
        for tool in TOOLS:
            assert "name" in tool
            assert tool["name"]

    def test_all_tools_have_description(self):
        for tool in TOOLS:
            assert "description" in tool
            assert len(tool["description"]) > 20, \
                f"Tool '{tool['name']}' description is too short"

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_tool_names_are_unique(self):
        names = [t["name"] for t in TOOLS]
        assert len(names) == len(set(names))

    def test_expected_tool_names_present(self):
        names = {t["name"] for t in TOOLS}
        expected = {
            "repo_metadata", "list_directory", "read_file",
            "search_code", "get_commits", "find_entrypoints",
        }
        assert names == expected

    def test_required_fields_are_lists(self):
        for tool in TOOLS:
            schema = tool["input_schema"]
            if "required" in schema:
                assert isinstance(schema["required"], list)
