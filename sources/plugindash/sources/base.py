"""What every source (GitHub, GitLab, ...) must provide.

Checks only talk to a RepoView, so a check written once works for every source.
Methods raise model.NotAvailable when a source can't supply something.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from ..model import Job, Release, Run, SecurityAlert, Workflow


def cached(method: Callable) -> Callable:
    """Remember a method's result per argument set for the length of one run."""
    @functools.wraps(method)
    def wrapper(self, *args):
        key = (method.__name__,) + args
        if key not in self._cache:
            self._cache[key] = method(self, *args)
        return self._cache[key]
    return wrapper


class RepoView:
    source = "base"

    def __init__(self) -> None:
        self._cache: dict[tuple, Any] = {}
        self.full_name = ""
        self.name = ""
        self.html_url = ""
        self.default_branch = "main"
        self.archived = False
        self.fork = False
        self.private = False
        self.pushed_at = None

    # --- Files -------------------------------------------------------------
    def file(self, path: str, ref: str | None = None) -> str | None:
        """Raw file content, or None when the file doesn't exist."""
        raise NotImplementedError

    def file_url(self, path: str, ref: str | None = None) -> str:
        raise NotImplementedError

    def list_dir(self, path: str) -> list[str] | None:
        """File names directly inside `path` on the default branch, or None when it doesn't exist."""
        raise NotImplementedError

    def readme(self) -> str | None:
        for name in ("README.md", "README.txt", "README", "readme.md"):
            text = self.file(name)
            if text is not None:
                return text
        return None

    # --- Releases ----------------------------------------------------------
    def latest_release(self) -> Release | None:
        raise NotImplementedError

    def previous_release(self) -> Release | None:
        """The published release before the latest one, or None."""
        raise NotImplementedError

    def commits_since(self, tag: str) -> int:
        """Commits on the default branch that are not in `tag`."""
        raise NotImplementedError

    def compare_url(self, tag: str) -> str:
        raise NotImplementedError

    # --- Issues ------------------------------------------------------------
    def open_issues(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def open_pull_requests(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def issues_url(self) -> str:
        raise NotImplementedError

    def pulls_url(self) -> str:
        raise NotImplementedError

    # --- CI ----------------------------------------------------------------
    def workflows(self) -> list[Workflow]:
        raise NotImplementedError

    def latest_run(self, workflow: Workflow) -> Run | None:
        """Latest finished run of `workflow` on the default branch."""
        raise NotImplementedError

    def run_jobs(self, run: Run) -> list[Job]:
        raise NotImplementedError

    def workflow_text(self, workflow: Workflow) -> str | None:
        return self.file(workflow.path)

    # --- Security ----------------------------------------------------------
    def security_alerts(self) -> list[SecurityAlert]:
        raise NotImplementedError

    def security_url(self) -> str:
        raise NotImplementedError


class Source:
    name = "base"

    def list_repos(self) -> list[RepoView]:
        raise NotImplementedError

    @property
    def api_calls(self) -> int:
        return 0
