"""Unit tests for agent/analyzer.py — Anthropic client is fully mocked."""
import json
from unittest.mock import MagicMock, patch

import pytest

from agent.fetcher import FileContent, RepoContext


def _make_ctx(**kwargs) -> RepoContext:
    defaults = dict(
        url="https://github.com/owner/repo",
        owner="owner",
        name="repo",
        description="A test repo",
        language="Python",
        stars=10,
        topics=["python"],
        default_branch="main",
        file_tree=["README.md", "main.py"],
        readme="# Test Repo",
        key_files=[FileContent(path="README.md", content="# Test Repo")],
        recent_commits=["2024-01-01  fix: something"],
    )
    defaults.update(kwargs)
    return RepoContext(**defaults)


def _make_response(payload: dict, stop_reason: str = "end_turn") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    thinking = MagicMock()
    thinking.type = "thinking"
    thinking.thinking = "I am reasoning..."
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = [thinking, block]
    return resp


class TestAnalyzerModel:
    def test_uses_haiku_model(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            mock_client = MockA.return_value
            mock_client.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_thinking_enabled(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        assert kwargs["thinking"]["type"] == "enabled"
        assert kwargs["thinking"]["budget_tokens"] == 8000

    def test_custom_thinking_budget(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx, thinking_budget=4000)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        assert kwargs["thinking"]["budget_tokens"] == 4000

    def test_system_prompt_has_cache_control(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        system = kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_single_api_call(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        assert MockA.return_value.messages.create.call_count == 1


class TestStripFences:
    def test_strips_json_fence(self):
        from agent.analyzer import _strip_fences
        text = "```json\n{}\n```"
        assert _strip_fences(text) == "{}"

    def test_strips_plain_fence(self):
        from agent.analyzer import _strip_fences
        text = "```\n{}\n```"
        assert _strip_fences(text) == "{}"

    def test_passthrough_bare_json(self):
        from agent.analyzer import _strip_fences
        text = '{"key": "value"}'
        assert _strip_fences(text) == text

    def test_model_fenced_output_parses(self, minimal_raw):
        import json
        ctx = _make_ctx()
        fenced_block = MagicMock()
        fenced_block.type = "text"
        fenced_block.text = f"```json\n{json.dumps(minimal_raw)}\n```"
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = [fenced_block]
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = resp
            from agent.analyzer import analyze
            from agent.models import AnalysisOutput
            result = analyze(ctx)
        assert isinstance(result, AnalysisOutput)


class TestAnalyzerOutput:
    def test_returns_analysis_output(self, minimal_raw):
        from agent.models import AnalysisOutput
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            result = analyze(ctx)
        assert isinstance(result, AnalysisOutput)

    def test_invalid_json_raises(self):
        ctx = _make_ctx()
        bad_block = MagicMock()
        bad_block.type = "text"
        bad_block.text = '{"bad": "schema"}'
        bad_resp = MagicMock()
        bad_resp.stop_reason = "end_turn"
        bad_resp.content = [bad_block]
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = bad_resp
            from agent.analyzer import analyze
            with pytest.raises(Exception):
                analyze(ctx)

    def test_no_text_block_raises(self):
        ctx = _make_ctx()
        thinking = MagicMock()
        thinking.type = "thinking"
        thinking.thinking = "..."
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = [thinking]
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = resp
            from agent.analyzer import analyze
            with pytest.raises(ValueError, match="no text block"):
                analyze(ctx)


class TestUserMessageContent:
    def test_message_contains_repo_name(self, minimal_raw):
        ctx = _make_ctx()
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        messages = kwargs["messages"]
        user_content = messages[0]["content"]
        assert "owner/repo" in user_content

    def test_message_contains_file_content(self, minimal_raw):
        ctx = _make_ctx(key_files=[FileContent(path="main.py", content="def hello(): pass")])
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        user_content = kwargs["messages"][0]["content"]
        assert "def hello(): pass" in user_content

    def test_message_contains_file_tree(self, minimal_raw):
        ctx = _make_ctx(file_tree=["README.md", "src/app.py"])
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        user_content = kwargs["messages"][0]["content"]
        assert "src/app.py" in user_content

    def test_message_contains_commits(self, minimal_raw):
        ctx = _make_ctx(recent_commits=["2024-01-01  feat: add oauth"])
        with patch("agent.analyzer.anthropic.Anthropic") as MockA:
            MockA.return_value.messages.create.return_value = _make_response(minimal_raw)
            from agent.analyzer import analyze
            analyze(ctx)
        kwargs = MockA.return_value.messages.create.call_args.kwargs
        user_content = kwargs["messages"][0]["content"]
        assert "feat: add oauth" in user_content


class TestRateLimitRetry:
    def test_retries_on_rate_limit(self, minimal_raw):
        import anthropic as anthropic_lib
        ctx = _make_ctx()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise anthropic_lib.RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429, headers={}),
                    body={},
                )
            return _make_response(minimal_raw)

        with patch("agent.analyzer.anthropic.Anthropic") as MockA, \
             patch("agent.analyzer.time.sleep"):
            MockA.return_value.messages.create.side_effect = side_effect
            from agent.analyzer import analyze
            result = analyze(ctx)

        assert call_count[0] == 2
        from agent.models import AnalysisOutput
        assert isinstance(result, AnalysisOutput)

    def test_raises_after_3_rate_limit_failures(self):
        import anthropic as anthropic_lib
        ctx = _make_ctx()

        def always_rate_limit(*args, **kwargs):
            raise anthropic_lib.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )

        with patch("agent.analyzer.anthropic.Anthropic") as MockA, \
             patch("agent.analyzer.time.sleep"):
            MockA.return_value.messages.create.side_effect = always_rate_limit
            from agent.analyzer import analyze
            with pytest.raises(anthropic_lib.RateLimitError):
                analyze(ctx)

        assert MockA.return_value.messages.create.call_count == 3
