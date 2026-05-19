from __future__ import annotations

import base64
import fnmatch
import re
from typing import Any

from github import Github, GithubException
from github.ContentFile import ContentFile

_MAX_FULL_LINES = 1500
_HEAD_LINES = 500
_TAIL_LINES = 200

_ENTRYPOINT_NAMES = {
    "main.py", "app.py", "server.py", "index.py", "run.py",
    "main.go", "main.rs", "main.ts", "index.ts", "index.js",
    "index.mjs", "app.ts", "app.js", "server.ts", "server.js",
    "__main__.py", "Dockerfile", "docker-compose.yml",
}

_ENTRYPOINT_DIRS = {"cmd", "bin", "src/cmd", "src/bin"}


class RepoClient:
    """Thin wrapper around PyGithub with a per-instance read cache."""

    def __new__(cls, *args: Any, **kwargs: Any) -> "RepoClient":
        instance = super().__new__(cls)
        instance._cache: dict[str, str] = {}
        return instance

    def __init__(self, repo_url: str, token: str | None = None) -> None:
        g = Github(token)
        slug = re.sub(r"https?://github\.com/", "", repo_url).rstrip("/")
        self.repo = g.get_repo(slug)

    # ── public methods ────────────────────────────────────────────────────────

    def repo_metadata(self) -> dict[str, Any]:
        r = self.repo
        try:
            root_contents = self.repo.get_contents("")
            root_entries = (
                [{"name": c.name, "type": c.type} for c in root_contents]
                if isinstance(root_contents, list)
                else [{"name": root_contents.name, "type": root_contents.type}]
            )
        except GithubException:
            root_entries = []

        return {
            "name": r.name,
            "full_name": r.full_name,
            "description": r.description or "",
            "language": r.language or "",
            "topics": r.get_topics(),
            "stars": r.stargazers_count,
            "forks": r.forks_count,
            "license": r.license.name if r.license else None,
            "default_branch": r.default_branch,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "root_entries": root_entries,
        }

    def read_file(self, path: str) -> str:
        if path in self._cache:
            return self._cache[path]

        try:
            contents = self.repo.get_contents(path)
        except GithubException as exc:
            raise FileNotFoundError(f"Cannot read '{path}': {exc}") from exc

        # Directory → list names
        if isinstance(contents, list):
            result = "\n".join(c.path for c in contents)
            self._cache[path] = result
            return result

        raw = base64.b64decode(contents.content).decode("utf-8", errors="replace")
        lines = raw.splitlines()

        if len(lines) > _MAX_FULL_LINES:
            omitted = len(lines) - _HEAD_LINES - _TAIL_LINES
            mid = f"\n... [{omitted} lines omitted] ...\n"
            raw = "\n".join(lines[:_HEAD_LINES]) + mid + "\n".join(lines[-_TAIL_LINES:])

        self._cache[path] = raw
        return raw

    def list_directory(self, path: str, depth: int = 2) -> list[dict[str, Any]]:
        depth = max(1, min(depth, 4))

        def _walk(p: str, d: int) -> list[dict[str, Any]]:
            if d == 0:
                return []
            try:
                entries = self.repo.get_contents(p)
            except GithubException:
                return []
            if not isinstance(entries, list):
                entries = [entries]
            result = []
            for c in entries:
                item: dict[str, Any] = {
                    "name": c.name,
                    "path": c.path,
                    "type": c.type,
                    "size": c.size,
                }
                if c.type == "dir":
                    item["children"] = _walk(c.path, d - 1)
                result.append(item)
            return result

        return _walk(path, depth)

    def search_code(
        self,
        pattern: str,
        file_glob: str = "*",
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        max_results = min(max_results, 50)

        try:
            import re as _re
            compiled = _re.compile(pattern)
        except _re.error:
            compiled = None

        results: list[dict[str, Any]] = []

        # Phase 1: GitHub code search API
        try:
            query = f"{pattern} repo:{self.repo.full_name}"
            g2 = Github()
            for item in list(g2.search_code(query))[:max_results]:
                if not fnmatch.fnmatch(item.name, file_glob):
                    continue
                try:
                    content = self.read_file(item.path)
                except FileNotFoundError:
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    hit = compiled.search(line) if compiled else (pattern in line)
                    if hit:
                        ctx = content.splitlines()[max(0, i - 2): i + 2]
                        results.append({
                            "file": item.path,
                            "line": i,
                            "match": line.strip(),
                            "context": ctx,
                        })
                        if len(results) >= max_results:
                            return results
        except Exception:
            pass

        # Phase 2: grep already-cached files (fallback / supplement)
        if not results:
            for path, content in self._cache.items():
                if not fnmatch.fnmatch(path.split("/")[-1], file_glob):
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    hit = compiled.search(line) if compiled else (pattern in line)
                    if hit:
                        results.append({"file": path, "line": i, "match": line.strip()})
                        if len(results) >= max_results:
                            return results

        return results

    def get_commits(self, n: int = 10) -> list[dict[str, Any]]:
        n = min(max(1, n), 30)
        commits = []
        for commit in self.repo.get_commits()[:n]:
            try:
                files = [f.filename for f in commit.files[:10]]
            except Exception:
                files = []
            commits.append({
                "sha": commit.sha[:8],
                "message": commit.commit.message.split("\n")[0],
                "author": commit.commit.author.name if commit.commit.author else "",
                "date": commit.commit.author.date.isoformat() if commit.commit.author else "",
                "files_changed": files,
            })
        return commits

    def find_entrypoints(self) -> dict[str, str]:
        """Return {path: first_80_lines} for likely entry-point files."""
        found: dict[str, str] = {}

        try:
            root = self.repo.get_contents("")
            if not isinstance(root, list):
                root = [root]
        except GithubException:
            return found

        for item in root:
            if item.name in _ENTRYPOINT_NAMES and item.type == "file":
                try:
                    raw = base64.b64decode(item.content).decode("utf-8", errors="replace")
                    found[item.path] = "\n".join(raw.splitlines()[:80])
                    self._cache[item.path] = raw  # populate cache for later use
                except Exception:
                    pass
            if item.type == "dir" and item.name in _ENTRYPOINT_DIRS:
                try:
                    sub = self.repo.get_contents(item.path)
                    if not isinstance(sub, list):
                        sub = [sub]
                    for subitem in sub:
                        if subitem.type == "file":
                            try:
                                raw = base64.b64decode(subitem.content).decode(
                                    "utf-8", errors="replace"
                                )
                                found[subitem.path] = "\n".join(raw.splitlines()[:80])
                                self._cache[subitem.path] = raw
                            except Exception:
                                pass
                except GithubException:
                    pass

        return found
