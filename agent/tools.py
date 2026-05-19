from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.github_client import RepoClient

TOOLS: list[dict[str, Any]] = [
    {
        "name": "repo_metadata",
        "description": (
            "Fetch top-level repository metadata: description, primary language, "
            "topics, star count, license, default branch, and a list of root-level "
            "files and folders. Always call this first, before any other tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "Full GitHub URL of the repository.",
                }
            },
            "required": ["repo_url"],
        },
    },
    {
        "name": "list_directory",
        "description": (
            "List all files and subdirectories at a given path within the repository. "
            "Returns names, types (file/dir), and sizes. Use depth=3 for the root scan "
            "and depth=1 when drilling into a specific subdirectory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the repo. Use empty string or '.' for root.",
                },
                "depth": {
                    "type": "integer",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 4,
                    "description": "Recursion depth.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a specific file. Returns raw text. "
            "Files longer than 1500 lines are automatically truncated to the first 500 "
            "and last 200 lines with a summary of the omitted middle section. "
            "Do not call this on binary files (.png, .jpg, .wasm, .bin, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the repo.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search for a regex pattern across all files in the repository. "
            "Returns file paths, line numbers, and up to 4 lines of surrounding context. "
            "Use this to trace imports, find handler registrations, locate config keys, "
            "or map data flow (e.g. pattern='router|handler|middleware|emit|subscribe')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex or literal string to search for.",
                },
                "file_glob": {
                    "type": "string",
                    "default": "*",
                    "description": "Limit search to files matching this glob, e.g. '*.py' or '*.ts'.",
                },
                "max_results": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 50,
                    "description": "Maximum number of matches to return.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_commits",
        "description": (
            "Retrieve the N most recent commits with their message, author, date, "
            "and list of files changed. Use this to identify the most actively "
            "modified files (high churn = likely important)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "default": 10,
                    "maximum": 30,
                    "description": "Number of commits to retrieve.",
                }
            },
        },
    },
    {
        "name": "find_entrypoints",
        "description": (
            "Heuristically locate likely entry-point files such as main.py, index.js, "
            "app.py, server.ts, Dockerfile, cmd/ directory contents, etc. "
            "Returns a dict of {path: first_80_lines}. Call this early to understand "
            "where execution starts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

_TOOL_MAP = {t["name"]: t for t in TOOLS}


def dispatch_tool(name: str, inputs: dict[str, Any], client: "RepoClient") -> dict[str, Any]:
    """Route a tool call to the correct RepoClient method.

    Always returns {"ok": bool, "data": ...} or {"ok": false, "error": "..."}.
    Never raises.
    """
    if name not in _TOOL_MAP:
        return {"ok": False, "error": f"Unknown tool: '{name}'. Valid tools: {list(_TOOL_MAP)}"}

    try:
        match name:
            case "repo_metadata":
                return {"ok": True, "data": client.repo_metadata()}
            case "list_directory":
                return {
                    "ok": True,
                    "data": client.list_directory(
                        inputs.get("path", ""),
                        inputs.get("depth", 2),
                    ),
                }
            case "read_file":
                return {"ok": True, "data": client.read_file(inputs["path"])}
            case "search_code":
                return {
                    "ok": True,
                    "data": client.search_code(
                        inputs["pattern"],
                        inputs.get("file_glob", "*"),
                        inputs.get("max_results", 20),
                    ),
                }
            case "get_commits":
                return {"ok": True, "data": client.get_commits(inputs.get("n", 10))}
            case "find_entrypoints":
                return {"ok": True, "data": client.find_entrypoints()}
            case _:
                return {"ok": False, "error": f"Unhandled tool: {name}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
