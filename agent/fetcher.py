from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any

from github import Github, GithubException

_ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "run.py", "manage.py", "__main__.py",
    "main.ts", "app.ts", "server.ts", "index.ts",
    "main.js", "app.js", "server.js", "index.js",
    "main.go", "main.rs", "main.rb",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
}

_CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "tsconfig.json",
    "Cargo.toml", "go.mod",
    "requirements.txt",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "mix.exs", "Gemfile",
}

_README_NAMES = {"README.md", "README.rst", "README.txt", "README", "readme.md"}

_MAX_FILE_LINES = 300
_MAX_FILES = 15
_MAX_TREE_ENTRIES = 600


@dataclass
class FileContent:
    path: str
    content: str
    truncated: bool = False


@dataclass
class RepoContext:
    url: str
    owner: str
    name: str
    description: str
    language: str
    stars: int
    topics: list[str]
    default_branch: str
    file_tree: list[str]
    readme: str
    key_files: list[FileContent]
    recent_commits: list[str]


def _decode(content_file: Any) -> str:
    try:
        return base64.b64decode(content_file.content).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _truncate(text: str, max_lines: int = _MAX_FILE_LINES) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    kept = "\n".join(lines[:max_lines])
    return kept + f"\n... [{len(lines) - max_lines} more lines omitted]", True


def _select_paths(all_paths: list[str]) -> list[str]:
    """Return up to _MAX_FILES paths ordered by priority."""
    selected: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> bool:
        if path not in seen and len(selected) < _MAX_FILES:
            seen.add(path)
            selected.append(path)
            return True
        return False

    # 1. README
    for p in all_paths:
        if os.path.basename(p) in _README_NAMES:
            add(p)

    # 2. Top-level entry points
    for p in all_paths:
        if "/" not in p and os.path.basename(p) in _ENTRY_POINT_NAMES:
            add(p)

    # 3. Top-level config / manifest files
    for p in all_paths:
        if "/" not in p and os.path.basename(p) in _CONFIG_NAMES:
            add(p)

    # 4. One CI workflow file
    for p in all_paths:
        if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
            add(p)
            break

    # 5. Top-level source files
    for p in all_paths:
        if "/" not in p and p.endswith((".py", ".ts", ".js", ".go", ".rs", ".rb")):
            add(p)

    # 6. Files one level deep in common source dirs
    for p in all_paths:
        parts = p.split("/")
        if len(parts) == 2 and parts[0] in ("src", "lib", "core", "app", "pkg", "agent", "output"):
            add(p)

    return selected


def fetch_repo(repo_url: str) -> RepoContext:
    """Fetch all content needed for analysis. No model involved."""
    token = os.environ.get("GITHUB_TOKEN")
    g = Github(token)

    slug = re.sub(r"https?://github\.com/", "", repo_url).rstrip("/")
    repo = g.get_repo(slug)

    description = repo.description or ""
    language = repo.language or "unknown"
    stars = repo.stargazers_count
    topics = list(repo.get_topics())
    default_branch = repo.default_branch

    # Full file tree (recursive git tree — one API call)
    try:
        tree = repo.get_git_tree(default_branch, recursive=True)
        all_paths = [item.path for item in tree.tree if item.type == "blob"]
    except GithubException:
        all_paths = []

    file_tree = all_paths[:_MAX_TREE_ENTRIES]

    # Fetch content for selected files
    paths_to_read = _select_paths(all_paths)
    key_files: list[FileContent] = []

    for path in paths_to_read:
        try:
            cf = repo.get_contents(path, ref=default_branch)
            raw = _decode(cf)
            content, truncated = _truncate(raw)
            key_files.append(FileContent(path=path, content=content, truncated=truncated))
        except GithubException:
            continue

    # README (use what's already fetched, or fetch separately)
    readme_content = ""
    for kf in key_files:
        if os.path.basename(kf.path) in _README_NAMES:
            readme_content = kf.content
            break
    if not readme_content:
        try:
            rf = repo.get_readme()
            readme_content, _ = _truncate(_decode(rf), max_lines=500)
        except GithubException:
            pass

    # Recent commits
    recent_commits: list[str] = []
    try:
        for c in repo.get_commits()[:15]:  # type: ignore[var-annotated]
            msg = (c.commit.message or "").split("\n")[0][:120]
            date = c.commit.author.date.strftime("%Y-%m-%d") if c.commit.author else "?"
            recent_commits.append(f"{date}  {msg}")
    except GithubException:
        pass

    return RepoContext(
        url=repo_url,
        owner=repo.owner.login,
        name=repo.name,
        description=description,
        language=language,
        stars=stars,
        topics=topics,
        default_branch=default_branch,
        file_tree=file_tree,
        readme=readme_content,
        key_files=key_files,
        recent_commits=recent_commits,
    )
