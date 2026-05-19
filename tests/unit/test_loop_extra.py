"""Extra unit tests to cover verbose mode, progress_callback, and edge cases in loop.py."""
import json
import pytest
from unittest.mock import MagicMock, patch, call


def _make_thinking_block():
    b = MagicMock()
    b.type = "thinking"
    b.thinking = "deep thought"
    return b


def _make_text_block(text: str):
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _make_tool_use_block(name="repo_metadata", tid="t1", inputs=None):
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.id = tid
    b.input = inputs or {}
    return b


def _end_turn(payload: dict):
    r = MagicMock()
    r.stop_reason = "end_turn"
    r.content = [_make_thinking_block(), _make_text_block(json.dumps(payload))]
    return r


def _tool_use_resp(name="repo_metadata", tid="t1"):
    r = MagicMock()
    r.stop_reason = "tool_use"
    r.content = [_make_tool_use_block(name, tid)]
    return r


class TestVerboseMode:
    def test_verbose_does_not_crash(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockA, \
             patch("agent.loop.RepoClient"):
            MockA.return_value.messages.create.return_value = _end_turn(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo", verbose=True)

    def test_verbose_with_tool_call_does_not_crash(self, minimal_raw):
        calls = [0]
        def side_effect(*a, **kw):
            calls[0] += 1
            if calls[0] == 1:
                return _tool_use_resp("repo_metadata", "t1")
            return _end_turn(minimal_raw)

        with patch("agent.loop.anthropic.Anthropic") as MockA, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.repo_metadata.return_value = {}
            MockA.return_value.messages.create.side_effect = side_effect
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo", verbose=True)


class TestProgressCallback:
    def test_callback_called_each_round(self, minimal_raw):
        calls = []

        def cb(round_num, status):
            calls.append((round_num, status))

        with patch("agent.loop.anthropic.Anthropic") as MockA, \
             patch("agent.loop.RepoClient"):
            MockA.return_value.messages.create.return_value = _end_turn(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo", progress_callback=cb)

        assert len(calls) >= 1
        assert calls[0][0] == 1  # round 1

    def test_callback_called_with_stop_reason(self, minimal_raw):
        statuses = []
        n_calls = [0]

        def cb(round_num, status):
            statuses.append(status)

        def side_effect(*a, **kw):
            n_calls[0] += 1
            if n_calls[0] == 1:
                return _tool_use_resp("repo_metadata")
            return _end_turn(minimal_raw)

        with patch("agent.loop.anthropic.Anthropic") as MockA, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.repo_metadata.return_value = {}
            MockA.return_value.messages.create.side_effect = side_effect
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo", progress_callback=cb)

        assert "thinking" in statuses
        assert "tool_use" in statuses


class TestUnexpectedStopReason:
    def test_unexpected_stop_reason_raises(self):
        bad_resp = MagicMock()
        bad_resp.stop_reason = "max_tokens"
        bad_resp.content = [_make_text_block("...")]

        with patch("agent.loop.anthropic.Anthropic") as MockA, \
             patch("agent.loop.RepoClient"):
            MockA.return_value.messages.create.return_value = bad_resp
            from agent.loop import run_agent
            with pytest.raises(ValueError, match="Unexpected stop_reason"):
                run_agent("https://github.com/owner/repo")


class TestGithubClientInit:
    def test_init_calls_get_repo(self):
        with patch("agent.github_client.Github") as MockGithub:
            mock_gh = MockGithub.return_value
            mock_gh.get_repo.return_value = MagicMock()
            from agent.github_client import RepoClient
            client = RepoClient("https://github.com/owner/repo", token="tok")
        MockGithub.assert_called_once_with("tok")
        mock_gh.get_repo.assert_called_once_with("owner/repo")

    def test_init_no_token(self):
        with patch("agent.github_client.Github") as MockGithub:
            MockGithub.return_value.get_repo.return_value = MagicMock()
            from agent.github_client import RepoClient
            RepoClient("https://github.com/owner/repo")
        MockGithub.assert_called_once_with(None)


class TestGetCommitsExtra:
    def test_get_commits_returns_list(self):
        from agent.github_client import RepoClient
        client = RepoClient.__new__(RepoClient)
        mock_repo = MagicMock()

        commit = MagicMock()
        commit.sha = "a" * 40
        commit.commit.message = "fix: something\ndetails"
        author = MagicMock()
        from datetime import datetime
        author.name = "Bob"
        author.date = datetime(2024, 6, 1)
        commit.commit.author = author
        fm = MagicMock()
        fm.filename = "src/main.py"
        commit.files = [fm]

        mock_repo.get_commits.return_value = [commit]
        client.repo = mock_repo
        result = client.get_commits(n=1)
        assert len(result) == 1
        assert result[0]["sha"] == "a" * 8
        assert result[0]["message"] == "fix: something"
        assert "src/main.py" in result[0]["files_changed"]

    def test_get_commits_no_author(self):
        from agent.github_client import RepoClient
        client = RepoClient.__new__(RepoClient)
        mock_repo = MagicMock()

        commit = MagicMock()
        commit.sha = "b" * 40
        commit.commit.message = "chore: update"
        commit.commit.author = None
        commit.files = []

        mock_repo.get_commits.return_value = [commit]
        client.repo = mock_repo
        result = client.get_commits(n=1)
        assert result[0]["author"] == ""
        assert result[0]["date"] == ""
