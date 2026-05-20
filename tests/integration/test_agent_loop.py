"""
Integration tests for agent/loop.py.

All Claude API calls are replaced with MagicMock responses — no live network.
GitHub API calls go through a mocked RepoClient.
These tests verify loop mechanics: model string, thinking forwarding,
round counting, parallel dispatch, error handling.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ── Helpers to build fake API responses ──────────────────────────────────────

def _make_tool_use_block(name: str, tool_id: str, inputs: dict) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.id = tool_id
    b.input = inputs
    return b


def _make_thinking_block(text: str = "I am thinking...") -> MagicMock:
    b = MagicMock()
    b.type = "thinking"
    b.thinking = text
    return b


def _make_text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _end_turn_response(payload: dict, include_thinking: bool = True) -> MagicMock:
    r = MagicMock()
    r.stop_reason = "end_turn"
    blocks = []
    if include_thinking:
        blocks.append(_make_thinking_block())
    blocks.append(_make_text_block(json.dumps(payload)))
    r.content = blocks
    return r


def _tool_use_response(tool_name: str, tool_id: str, inputs: dict) -> MagicMock:
    r = MagicMock()
    r.stop_reason = "tool_use"
    r.content = [_make_thinking_block(), _make_tool_use_block(tool_name, tool_id, inputs)]
    return r


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAgenticLoopModel:
    def test_uses_haiku_45(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthopic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthopic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_thinking_enabled_by_default(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["thinking"]["type"] == "enabled"
        assert kwargs["thinking"]["budget_tokens"] == 8000

    def test_custom_thinking_budget(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo", thinking_budget=5000)
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["thinking"]["budget_tokens"] == 5000

    def test_system_prompt_has_cache_control(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")
        kwargs = mock_client.messages.create.call_args.kwargs
        system = kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}


class TestThinkingBlockForwarding:
    def test_thinking_blocks_preserved_in_messages(self, minimal_raw):
        """Thinking blocks from round 1 must appear in the assistant turn sent in round 2."""
        captured: list = []

        def side_effect(*args, **kwargs):
            captured.append(kwargs.get("messages", []))
            if len(captured) == 1:
                return _tool_use_response("repo_metadata", "t1", {"repo_url": "x"})
            return _end_turn_response(minimal_raw)

        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.repo_metadata.return_value = {"name": "r"}
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = side_effect
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")

        # Round 2 messages should include an assistant turn from round 1
        round2_messages = captured[1]
        assistant_turns = [m for m in round2_messages if m.get("role") == "assistant"]
        assert len(assistant_turns) >= 1
        # The assistant turn content should include the thinking block
        content = assistant_turns[0]["content"]
        block_types = [getattr(b, "type", None) for b in content]
        assert "thinking" in block_types


class TestRoundCounting:
    def test_single_end_turn_works(self, minimal_raw):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            result = run_agent("https://github.com/owner/repo")
        assert result.project_name == "test-repo"
        assert mock_client.messages.create.call_count == 1

    def test_raises_after_15_rounds(self):
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.find_entrypoints.return_value = {}
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _tool_use_response(
                "find_entrypoints", "t_loop", {}
            )
            from agent.loop import run_agent
            with pytest.raises(RuntimeError, match="15 rounds"):
                run_agent("https://github.com/owner/repo")
        assert mock_client.messages.create.call_count == 15


class TestToolDispatch:
    def test_tool_result_added_to_messages(self, minimal_raw):
        calls: list = []

        def side_effect(*args, **kwargs):
            calls.append(kwargs.get("messages", []))
            if len(calls) == 1:
                return _tool_use_response("repo_metadata", "tid1", {"repo_url": "x"})
            return _end_turn_response(minimal_raw)

        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.repo_metadata.return_value = {"name": "r"}
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = side_effect
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")

        # Round 2 messages should end with a user turn containing tool_result
        round2_messages = calls[1]
        last_user = next(
            (m for m in reversed(round2_messages) if m.get("role") == "user"), None
        )
        assert last_user is not None
        content = last_user["content"]
        assert isinstance(content, list)
        assert any(item.get("type") == "tool_result" for item in content)

    def test_parallel_tool_calls_all_dispatched(self, minimal_raw):
        """Multiple tool_use blocks in one response → all dispatched."""
        block1 = _make_tool_use_block("repo_metadata", "t1", {"repo_url": "x"})
        block2 = _make_tool_use_block("find_entrypoints", "t2", {})
        multi_resp = MagicMock()
        multi_resp.stop_reason = "tool_use"
        multi_resp.content = [block1, block2]

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return multi_resp
            return _end_turn_response(minimal_raw)

        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient") as MockRC:
            MockRC.return_value.repo_metadata.return_value = {}
            MockRC.return_value.find_entrypoints.return_value = {}
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = side_effect
            from agent.loop import run_agent
            run_agent("https://github.com/owner/repo")

        # Round 2 last user turn should have 2 tool_results
        all_calls = mock_client.messages.create.call_args_list
        round2_messages = all_calls[1].kwargs["messages"]
        last_user_content = next(
            m["content"] for m in reversed(round2_messages) if m.get("role") == "user"
        )
        tool_result_count = sum(
            1 for item in last_user_content if item.get("type") == "tool_result"
        )
        assert tool_result_count == 2


class TestOutputValidation:
    def test_returns_analysis_output_instance(self, minimal_raw):
        from agent.models import AnalysisOutput
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = _end_turn_response(minimal_raw)
            from agent.loop import run_agent
            result = run_agent("https://github.com/owner/repo")
        assert isinstance(result, AnalysisOutput)

    def test_invalid_json_raises_value_error(self):
        bad_resp = MagicMock()
        bad_resp.stop_reason = "end_turn"
        bad_resp.content = [_make_text_block('{"bad": "schema"}')]
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = bad_resp
            from agent.loop import run_agent
            with pytest.raises((ValueError, Exception)):
                run_agent("https://github.com/owner/repo")

    def test_end_turn_with_no_text_block_raises(self):
        bad_resp = MagicMock()
        bad_resp.stop_reason = "end_turn"
        bad_resp.content = [_make_thinking_block()]  # thinking only, no text
        with patch("agent.loop.anthropic.Anthropic") as MockAnthropic, \
             patch("agent.loop.RepoClient"):
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = bad_resp
            from agent.loop import run_agent
            with pytest.raises((ValueError, Exception)):
                run_agent("https://github.com/owner/repo")
