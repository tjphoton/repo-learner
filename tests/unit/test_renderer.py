import pathlib
import pytest
from output.renderer import render_html


class TestRendererSections:
    def test_all_six_section_ids_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        for section_id in ("overview", "directory", "key-files", "data-flow", "innovation", "rebuild"):
            assert f'id="{section_id}"' in html, f"Missing section id='{section_id}'"

    def test_project_name_in_title(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "test-repo" in html

    def test_one_liner_in_html(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert minimal_analysis_output.one_liner in html

    def test_tech_stack_tags_rendered(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        for tech in minimal_analysis_output.tech_stack:
            assert tech in html

    def test_complexity_badge_rendered(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert minimal_analysis_output.estimated_complexity in html


class TestMermaidDiagrams:
    def test_at_least_two_mermaid_divs(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert html.count('class="mermaid"') >= 2

    def test_architecture_mermaid_content_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        # The graph TB content should appear inside a mermaid div
        assert "graph TB" in html

    def test_data_flow_mermaid_content_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "sequenceDiagram" in html


class TestKeyFiles:
    def test_all_10_key_file_paths_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        for kf in minimal_analysis_output.key_files:
            assert kf.path in html

    def test_key_file_excerpts_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        # At least one excerpt should appear
        assert "def main" in html or "# File" in html

    def test_language_class_applied(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "language-" in html


class TestRebuildSection:
    def test_copy_button_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "Copy" in html

    def test_prompt_content_present(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        for phase in minimal_analysis_output.rebuild_phases:
            assert phase.title in html

    def test_phase_numbers_rendered(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        for phase in minimal_analysis_output.rebuild_phases:
            assert f"Phase {phase.phase}" in html

    def test_gotchas_rendered(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        # Phase 1 has a gotcha
        assert "Use async drivers" in html


class TestSelfContainment:
    def test_no_cdn_jsdelivr(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "cdn.jsdelivr.net" not in html

    def test_has_mermaid_script(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "mermaid" in html.lower()

    def test_has_prism_reference(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert "prism" in html.lower()


class TestFileOutput:
    def test_writes_to_path(self, minimal_analysis_output, tmp_path):
        out = tmp_path / "report.html"
        render_html(minimal_analysis_output, output_path=out)
        assert out.exists()

    def test_output_file_size(self, minimal_analysis_output, tmp_path):
        out = tmp_path / "report.html"
        render_html(minimal_analysis_output, output_path=out)
        assert out.stat().st_size > 5_000

    def test_creates_parent_dirs(self, minimal_analysis_output, tmp_path):
        out = tmp_path / "nested" / "deep" / "report.html"
        render_html(minimal_analysis_output, output_path=out)
        assert out.exists()

    def test_returns_html_string(self, minimal_analysis_output):
        html = render_html(minimal_analysis_output)
        assert isinstance(html, str)
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_output_path_none_does_not_write(self, minimal_analysis_output, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        render_html(minimal_analysis_output, output_path=None)
        # No file should appear in tmp_path (output_path=None means no write)
        html_files = list(tmp_path.glob("*.html"))
        assert len(html_files) == 0
