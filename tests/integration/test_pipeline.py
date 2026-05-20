"""
Integration tests for the fetch → analyze pipeline.
All external calls (GitHub API, Anthropic API) are mocked.
Verifies that fetcher output flows correctly into the analyzer.
"""
import base64
import json
from unittest.mock import MagicMock, patch




def _encoded(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _make_github_mock(paths: list[str], content: str = "# hello") -> MagicMock:
    mock_repo = MagicMock()
    mock_repo.description = "Test repo"
    mock_repo.language = "Python"
    mock_repo.stargazers_count = 1
    mock_repo.forks_count = 0
    mock_repo.default_branch = "main"
    mock_repo.owner.login = "owner"
    mock_repo.name = "repo"
    mock_repo.get_topics.return_value = []

    tree_items = []
    for p in paths:
        item = MagicMock()
        item.path = p
        item.type = "blob"
        tree_items.append(item)
    mock_tree = MagicMock()
    mock_tree.tree = tree_items
    mock_repo.get_git_tree.return_value = mock_tree

    cf = MagicMock()
    cf.content = _encoded(content)
    mock_repo.get_contents.return_value = cf

    commit = MagicMock()
    commit.commit.message = "fix: bug"
    commit.commit.author.date.strftime.return_value = "2024-01-01"
    mock_repo.get_commits.return_value = [commit]

    mock_g = MagicMock()
    mock_g.get_repo.return_value = mock_repo
    return mock_g


def _make_anthropic_mock(payload: dict) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = resp
    mock_a = MagicMock()
    mock_a.return_value = mock_client
    return mock_a


class TestFetchToAnalyzePipeline:
    def test_full_pipeline_returns_analysis_output(self, minimal_raw):
        from agent.models import AnalysisOutput
        mock_g = _make_github_mock(["README.md", "main.py"], content="# Hello")
        mock_a = _make_anthropic_mock(minimal_raw)

        with patch("agent.fetcher.Github", return_value=mock_g), \
             patch("agent.analyzer.anthropic.Anthropic", mock_a):
            from agent.fetcher import fetch_repo
            from agent.analyzer import analyze
            ctx = fetch_repo("https://github.com/owner/repo")
            result = analyze(ctx)

        assert isinstance(result, AnalysisOutput)

    def test_fetched_files_appear_in_analyzer_prompt(self, minimal_raw):
        mock_g = _make_github_mock(["README.md"], content="# Special content XYZ")
        mock_a = _make_anthropic_mock(minimal_raw)

        with patch("agent.fetcher.Github", return_value=mock_g), \
             patch("agent.analyzer.anthropic.Anthropic", mock_a):
            from agent.fetcher import fetch_repo
            from agent.analyzer import analyze
            ctx = fetch_repo("https://github.com/owner/repo")
            analyze(ctx)

        kwargs = mock_a.return_value.messages.create.call_args.kwargs
        user_content = kwargs["messages"][0]["content"]
        assert "Special content XYZ" in user_content

    def test_analyzer_makes_exactly_one_api_call(self, minimal_raw):
        mock_g = _make_github_mock(["README.md"])
        mock_a = _make_anthropic_mock(minimal_raw)

        with patch("agent.fetcher.Github", return_value=mock_g), \
             patch("agent.analyzer.anthropic.Anthropic", mock_a):
            from agent.fetcher import fetch_repo
            from agent.analyzer import analyze
            ctx = fetch_repo("https://github.com/owner/repo")
            analyze(ctx)

        assert mock_a.return_value.messages.create.call_count == 1

    def test_file_tree_flows_into_prompt(self, minimal_raw):
        mock_g = _make_github_mock(["README.md", "src/core.py", "src/utils.py"])
        mock_a = _make_anthropic_mock(minimal_raw)

        with patch("agent.fetcher.Github", return_value=mock_g), \
             patch("agent.analyzer.anthropic.Anthropic", mock_a):
            from agent.fetcher import fetch_repo
            from agent.analyzer import analyze
            ctx = fetch_repo("https://github.com/owner/repo")
            analyze(ctx)

        kwargs = mock_a.return_value.messages.create.call_args.kwargs
        user_content = kwargs["messages"][0]["content"]
        assert "src/core.py" in user_content
        assert "src/utils.py" in user_content
