import pytest
from pydantic import ValidationError
from agent.models import AnalysisOutput, KeyFile, validate_output, output_schema_json


# ── helpers ──────────────────────────────────────────────────────────────────

def _raw(minimal_raw: dict, **overrides) -> dict:
    d = minimal_raw.copy()
    d.update(overrides)
    return d


def _kf(rank: int = 1, path: str = "src/a.py", mermaid_node: str = "A") -> dict:
    return {
        "path": path,
        "rank": rank,
        "reason": "reason",
        "excerpt": "# code",
        "mermaid_node": mermaid_node,
    }


# ── AnalysisOutput happy-path ─────────────────────────────────────────────────

class TestAnalysisOutputValid:
    def test_valid_passes(self, minimal_raw):
        out = AnalysisOutput.model_validate(minimal_raw)
        assert out.project_name == "test-repo"

    def test_tech_stack_preserved(self, minimal_raw):
        out = AnalysisOutput.model_validate(minimal_raw)
        assert "Python" in out.tech_stack

    def test_key_files_sorted_by_rank(self, minimal_raw):
        out = AnalysisOutput.model_validate(minimal_raw)
        ranks = [f.rank for f in out.key_files]
        assert ranks == sorted(ranks)

    def test_complexity_literals(self, minimal_raw):
        for val in ("small", "medium", "large", "very-large"):
            out = AnalysisOutput.model_validate({**minimal_raw, "estimated_complexity": val})
            assert out.estimated_complexity == val


# ── Required field missing ────────────────────────────────────────────────────

class TestMissingRequiredFields:
    @pytest.mark.parametrize("field", [
        "repo_url", "project_name", "one_liner", "purpose",
        "tech_stack", "architecture_mermaid", "directory_structure",
        "key_files", "data_flow_mermaid", "data_flow_steps",
        "innovation_points", "rebuild_phases", "estimated_complexity",
    ])
    def test_missing_raises(self, minimal_raw, field):
        data = minimal_raw.copy()
        del data[field]
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate(data)


# ── key_files constraints ─────────────────────────────────────────────────────

class TestKeyFilesConstraints:
    def test_exactly_10_required(self, minimal_raw):
        data = {**minimal_raw, "key_files": [_kf(1)] * 5}
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate(data)

    def test_more_than_10_rejected(self, minimal_raw):
        data = {**minimal_raw, "key_files": [_kf(i + 1, f"f{i}.py", f"N{i}") for i in range(11)]}
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate(data)

    def test_rank_below_1_rejected(self, minimal_raw):
        files = [_kf(i + 1, f"f{i}.py", f"N{i}") for i in range(10)]
        files[0]["rank"] = 0
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "key_files": files})

    def test_rank_above_10_rejected(self, minimal_raw):
        files = [_kf(i + 1, f"f{i}.py", f"N{i}") for i in range(10)]
        files[9]["rank"] = 99
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "key_files": files})

    def test_duplicate_ranks_rejected(self, minimal_raw):
        files = [_kf(1, f"f{i}.py", f"N{i}") for i in range(10)]  # all rank=1
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "key_files": files})

    def test_mermaid_node_empty_rejected(self, minimal_raw):
        files = [_kf(i + 1, f"f{i}.py", f"N{i}") for i in range(10)]
        files[0]["mermaid_node"] = ""
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "key_files": files})


# ── rebuild_phases constraints ────────────────────────────────────────────────

class TestRebuildPhasesConstraints:
    def test_fewer_than_4_rejected(self, minimal_raw):
        data = {**minimal_raw, "rebuild_phases": [
            {"phase": i, "title": "T", "description": "D", "prompt": "P" * 10, "gotchas": []}
            for i in range(3)
        ]}
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate(data)

    def test_4_phases_accepted(self, minimal_raw):
        out = AnalysisOutput.model_validate(minimal_raw)
        assert len(out.rebuild_phases) == 4


# ── estimated_complexity ──────────────────────────────────────────────────────

class TestComplexityEnum:
    def test_invalid_value_rejected(self, minimal_raw):
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "estimated_complexity": "galaxy-brained"})

    def test_case_sensitive(self, minimal_raw):
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate({**minimal_raw, "estimated_complexity": "Medium"})


# ── validate_output helper ────────────────────────────────────────────────────

class TestValidateOutput:
    def test_valid_dict_returns_model(self, minimal_raw):
        result = validate_output(minimal_raw)
        assert isinstance(result, AnalysisOutput)

    def test_invalid_dict_raises_value_error(self):
        with pytest.raises(ValueError, match="Output validation failed"):
            validate_output({"bad": "data"})

    def test_error_message_contains_details(self):
        with pytest.raises(ValueError, match="Output validation failed"):
            validate_output({})


# ── output_schema_json ────────────────────────────────────────────────────────

class TestOutputSchemaJson:
    def test_returns_valid_json_string(self):
        import json
        schema_str = output_schema_json()
        parsed = json.loads(schema_str)
        assert "properties" in parsed

    def test_schema_contains_key_fields(self):
        schema_str = output_schema_json()
        for field in ("key_files", "rebuild_phases", "architecture_mermaid"):
            assert field in schema_str


# ── KeyFile model ─────────────────────────────────────────────────────────────

class TestKeyFile:
    def test_valid(self):
        kf = KeyFile(path="a.py", rank=1, reason="r", excerpt="x", mermaid_node="N1")
        assert kf.rank == 1

    def test_rank_0_rejected(self):
        with pytest.raises(ValidationError):
            KeyFile(path="a.py", rank=0, reason="r", excerpt="x", mermaid_node="N")

    def test_rank_11_rejected(self):
        with pytest.raises(ValidationError):
            KeyFile(path="a.py", rank=11, reason="r", excerpt="x", mermaid_node="N")
