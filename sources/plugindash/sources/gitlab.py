"""Self-hosted GitLab source (API v4).

GitLab has one CI file (.gitlab-ci.yml) rather than several workflows, so it is
presented as a single workflow. Jobs marked `allow_failure: true` are reported
with allowed_failure=True, which the CI check treats like a Moodle `main` cell.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime
from typing import Any

from ..http import AuthError, Client, NotFound
from ..model import Job, NotAvailable, Release, Run, SecurityAlert, Workflow
from .base import RepoView, Source, cached

_PIPELINE_DONE = {"success", "failed", "canceled", "skipped"}
_CI_FILE = ".gitlab-ci.yml"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalise_status(value: str | None) -> str:
    return {"success": "success", "failed": "failure", "canceled": "cancelled"}.get(value or "", "other")


class GitLabRepo(RepoView):
    source = "gitlab"

    def __init__(self, client: Client, data: dict[str, Any]):
        super().__init__()
        self.client = client
        self.project_id = data["id"]
        self.full_name = data["path_with_namespace"]
        self.name = data["path"]
        self.html_url = data["web_url"]
        self.default_branch = data.get("default_branch") or "main"
        self.archived = bool(data.get("archived"))
        self.fork = bool(data.get("forked_from_project"))
        self.private = data.get("visibility") != "public"
        self.pushed_at = parse_time(data.get("last_activity_at"))

    @property
    def _api(self) -> str:
        return f"/projects/{self.project_id}"

    # Files.
    @cached
    def file(self, path: str, ref: str | None = None) -> str | None:
        encoded = urllib.parse.quote(path, safe="")
        try:
            return self.client.get_text(
                f"{self._api}/repository/files/{encoded}/raw", {"ref": ref or self.default_branch},
            )
        except NotFound:
            return None

    def file_url(self, path: str, ref: str | None = None) -> str:
        return f"{self.html_url}/-/blob/{ref or self.default_branch}/{path}"

    # Releases.
    @cached
    def latest_release(self) -> Release | None:
        data = self.client.get_json(f"{self._api}/releases", {"per_page": 1, "order_by": "released_at"})
        if not data:
            return None
        rel = data[0]
        links = (rel.get("assets") or {}).get("links") or []
        assets = [{"name": link.get("name", ""), "url": link.get("url", "")} for link in links]
        return Release(
            tag=rel["tag_name"], name=rel.get("name") or rel["tag_name"],
            url=(rel.get("_links") or {}).get("self"), published_at=parse_time(rel.get("released_at")),
            assets=assets,
        )

    @cached
    def commits_since(self, tag: str) -> int:
        data = self.client.get_json(
            f"{self._api}/repository/compare", {"from": tag, "to": self.default_branch, "straight": "false"},
        )
        return len((data or {}).get("commits") or [])

    def compare_url(self, tag: str) -> str:
        return f"{self.html_url}/-/compare/{tag}...{self.default_branch}"

    # Issues and merge requests.
    @cached
    def open_issues(self) -> list[dict[str, Any]]:
        return self.client.get_paged(f"{self._api}/issues", {"state": "opened", "per_page": 100})

    @cached
    def open_pull_requests(self) -> list[dict[str, Any]]:
        return self.client.get_paged(f"{self._api}/merge_requests", {"state": "opened", "per_page": 100})

    def issues_url(self) -> str:
        return f"{self.html_url}/-/issues"

    def pulls_url(self) -> str:
        return f"{self.html_url}/-/merge_requests"

    # CI.
    @cached
    def workflows(self) -> list[Workflow]:
        if self.file(_CI_FILE) is None:
            return []
        return [Workflow(id="gitlab-ci", name="GitLab CI", path=_CI_FILE, state="active")]

    @cached
    def latest_run(self, workflow: Workflow) -> Run | None:
        pipelines = self.client.get_json(
            f"{self._api}/pipelines", {"ref": self.default_branch, "per_page": 10, "order_by": "id"},
        )
        for pipe in pipelines or []:
            if pipe.get("status") not in _PIPELINE_DONE:
                continue
            return Run(
                id=str(pipe["id"]), conclusion=normalise_status(pipe.get("status")),
                created_at=parse_time(pipe.get("created_at")), url=pipe.get("web_url"),
            )
        return None

    @cached
    def run_jobs(self, run: Run) -> list[Job]:
        jobs = self.client.get_paged(f"{self._api}/pipelines/{run.id}/jobs", {"per_page": 100})
        return [
            Job(name=j.get("name", ""), conclusion=normalise_status(j.get("status")),
                allowed_failure=bool(j.get("allow_failure")))
            for j in jobs
        ]

    # Security.
    def security_alerts(self) -> list[SecurityAlert]:
        raise NotAvailable("Dependency alerts need GitLab Ultimate; not available on GitLab CE")

    def security_url(self) -> str:
        return f"{self.html_url}/-/security/vulnerability_report"


class GitLabSource(Source):
    name = "gitlab"

    def __init__(self, cfg: dict[str, Any], client: Client | None = None):
        self.cfg = cfg
        self.client = client or Client(
            f"{cfg['gitlab_url']}/api/v4", headers={"PRIVATE-TOKEN": cfg["gitlab_token"]},
        )

    @property
    def api_calls(self) -> int:
        return self.client.calls

    def list_repos(self) -> list[RepoView]:
        try:
            data = self.client.get_paged("/projects", {"membership": "true", "per_page": 100, "order_by": "path"})
        except AuthError as err:
            raise AuthError(err.status, err.url, "GitLab rejected the token (expired or wrong scope)") from err
        return [GitLabRepo(self.client, item) for item in data]
