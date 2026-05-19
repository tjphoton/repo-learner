"""
E2E tests — run with: uv run pytest -m slow tests/e2e/

Requires ANTHROPIC_API_KEY and GITHUB_TOKEN env vars.
These call real APIs and cost ~$0.11 each. Only run on main branch in CI.
"""
import os
import pytest

pytestmark = pytest.mark.slow

SMALL_REPO = "https://github.com/anthropics/anthropic-quickstarts"
NO_README_REPO = "https://github.com/anthropics/anthropic-sdk-python"


@pytest.fixture(autouse=True)
def require_keys():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    if not os.environ.get("GITHUB_TOKEN"):
        pytest.skip("GITHUB_TOKEN not set")


class TestSmallRepo:
    @pytest.fixture(scope="class")
    def result(self):
        from agent.loop import run_agent
        return run_agent(SMALL_REPO, thinking_budget=8000)

    def test_returns_analysis_output(self, result):
        from agent.models import AnalysisOutput
        assert isinstance(result, AnalysisOutput)

    def test_project_name_populated(self, result):
        assert result.project_name

    def test_one_liner_populated(self, result):
        assert len(result.one_liner) > 10

    def test_purpose_populated(self, result):
        assert len(result.purpose) > 20

    def test_tech_stack_non_empty(self, result):
        assert len(result.tech_stack) >= 1

    def test_architecture_mermaid_valid(self, result):
        assert result.architecture_mermaid.startswith(("graph TB", "graph LR", "graph TD"))

    def test_data_flow_mermaid_valid(self, result):
        assert result.data_flow_mermaid.startswith("sequenceDiagram")

    def test_exactly_10_key_files(self, result):
        assert len(result.key_files) == 10

    def test_key_file_ranks_unique(self, result):
        ranks = [f.rank for f in result.key_files]
        assert len(ranks) == len(set(ranks))

    def test_key_file_ranks_in_range(self, result):
        for f in result.key_files:
            assert 1 <= f.rank <= 10

    def test_key_file_reasons_non_empty(self, result):
        for f in result.key_files:
            assert len(f.reason) > 5

    def test_at_least_4_rebuild_phases(self, result):
        assert len(result.rebuild_phases) >= 4

    def test_rebuild_prompts_non_empty(self, result):
        for phase in result.rebuild_phases:
            assert len(phase.prompt) >= 50, f"Phase {phase.phase} prompt too short"

    def test_innovation_points_present(self, result):
        assert len(result.innovation_points) >= 1

    def test_complexity_valid(self, result):
        assert result.estimated_complexity in ("small", "medium", "large", "very-large")

    def test_html_renders_successfully(self, result):
        from output.renderer import render_html
        html = render_html(result)
        assert len(html) > 10_000

    def test_html_self_contained(self, result):
        from output.renderer import render_html
        html = render_html(result)
        assert "cdn.jsdelivr.net" not in html

    def test_html_has_all_sections(self, result):
        from output.renderer import render_html
        html = render_html(result)
        for section_id in ("overview", "directory", "key-files", "data-flow", "innovation", "rebuild"):
            assert f'id="{section_id}"' in html


class TestRepoWithNoReadme:
    def test_handles_gracefully(self):
        from agent.loop import run_agent
        result = run_agent(NO_README_REPO, thinking_budget=8000)
        assert result.purpose  # should infer purpose from code even without README
        assert result.project_name
