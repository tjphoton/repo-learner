import pytest
from agent.models import (
    AnalysisOutput,
)


def _minimal_raw() -> dict:
    return {
        "repo_url": "https://github.com/owner/repo",
        "project_name": "test-repo",
        "one_liner": "A short description of the project.",
        "purpose": "Longer purpose statement explaining what this project does.",
        "tech_stack": ["Python", "FastAPI", "PostgreSQL"],
        "architecture_mermaid": "graph TB\n  A[Client] --> B[Server]\n  B --> C[DB]",
        "directory_structure": [
            {"path": "src", "annotation": "main source code", "type": "dir"},
            {"path": "tests", "annotation": "test suite", "type": "dir"},
        ],
        "key_files": [
            {
                "path": f"src/file_{i}.py",
                "rank": i + 1,
                "reason": f"Important because of reason {i}",
                "excerpt": f"# File {i}\ndef main():\n    pass",
                "mermaid_node": f"F{i}",
            }
            for i in range(10)
        ],
        "data_flow_mermaid": (
            "sequenceDiagram\n"
            "  participant C as Client\n"
            "  participant S as Server\n"
            "  C->>S: request\n"
            "  S-->>C: response"
        ),
        "data_flow_steps": [
            {"source": "Client", "target": "Server", "label": "HTTP request", "file_ref": "src/server.py"},
        ],
        "innovation_points": [
            {
                "title": "Novel feature",
                "conventional": "Old approach",
                "this_project": "New approach",
                "why_matters": "Because it is faster",
            }
        ],
        "rebuild_phases": [
            {
                "phase": 1,
                "title": "Bootstrap",
                "description": "Set up the project structure.",
                "prompt": "Create a Python project with FastAPI and PostgreSQL. Include a basic CRUD API.",
                "gotchas": ["Use async drivers for PostgreSQL"],
            },
            {
                "phase": 2,
                "title": "Core logic",
                "description": "Implement the main business logic.",
                "prompt": "Add business logic layer with service classes and repository pattern.",
                "gotchas": [],
            },
            {
                "phase": 3,
                "title": "Testing",
                "description": "Add comprehensive tests.",
                "prompt": "Write pytest tests with fixtures for database and API client.",
                "gotchas": ["Use test database, not production"],
            },
            {
                "phase": 4,
                "title": "Deployment",
                "description": "Containerise and deploy.",
                "prompt": "Create Dockerfile and docker-compose.yml for the application.",
                "gotchas": [],
            },
        ],
        "estimated_complexity": "medium",
    }


@pytest.fixture
def minimal_raw() -> dict:
    return _minimal_raw()


@pytest.fixture
def minimal_analysis_output() -> AnalysisOutput:
    return AnalysisOutput.model_validate(_minimal_raw())
