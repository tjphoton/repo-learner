from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class KeyFile(BaseModel):
    path: str
    rank: Annotated[int, Field(ge=1, le=10)]
    reason: str
    excerpt: str
    mermaid_node: Annotated[str, Field(min_length=1)]


class DataFlowStep(BaseModel):
    source: str
    target: str
    label: str
    file_ref: str


class InnovationPoint(BaseModel):
    title: str
    conventional: str
    this_project: str
    why_matters: str


class DirectoryEntry(BaseModel):
    path: str
    annotation: str
    type: str = "dir"  # "dir" | "file"


class RebuildPhase(BaseModel):
    phase: int
    title: str
    description: str
    prompt: str
    gotchas: list[str] = Field(default_factory=list)


class AnalysisOutput(BaseModel):
    repo_url: str
    project_name: str
    one_liner: str
    purpose: str
    tech_stack: list[str]
    architecture_mermaid: str
    directory_structure: list[DirectoryEntry]
    key_files: Annotated[list[KeyFile], Field(min_length=10, max_length=10)]
    data_flow_mermaid: str
    data_flow_steps: list[DataFlowStep]
    innovation_points: list[InnovationPoint]
    rebuild_phases: Annotated[list[RebuildPhase], Field(min_length=4)]
    estimated_complexity: Literal["small", "medium", "large", "very-large"]

    @field_validator("key_files")
    @classmethod
    def ranks_must_be_unique(cls, files: list[KeyFile]) -> list[KeyFile]:
        ranks = [f.rank for f in files]
        if len(ranks) != len(set(ranks)):
            raise ValueError("key_files ranks must be unique")
        return files


def validate_output(raw: dict) -> AnalysisOutput:
    """Parse and validate a raw dict from the agent. Raises ValueError on failure."""
    try:
        return AnalysisOutput.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Output validation failed: {exc}") from exc


def output_schema_json() -> str:
    """Return the JSON schema for AnalysisOutput (injected into the system prompt)."""
    return json.dumps(AnalysisOutput.model_json_schema(), indent=2)
