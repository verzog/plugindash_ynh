"""GitHub source (REST API v3)."""

from __future__ import annotations

import urllib.parse
from datetime import datetime
from typing import Any

from ..http import AuthError, Client, HttpError, NotFound
from ..model import Job, NotAvailable, Release, Run, SecurityAlert, Workflow
from .base import RepoView, Source, cached

_FAILED = {"failure", "timed_out", "startup_failure"}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalise_conclusion(value: str | None) -> str:
    if value == "success":
        return "success"
    if value in _FAILED:
        return "failure"
    if value == "cancelled":
        return "cancelled"
    return "other"


class GitHubRepo(RepoView):
    source = "github"

    def __init__(self, client: Client, data: dict[str, Any]):
        super().__init__()
        self.client = client
        self.full_name = data["full_name"]
        self.name = data["name"]
        self.html_url = data["html_url"]
        self.default_branch = data.get("default_branch") or "main"
        self.archived = bool(data.get("archived"))
        self.fork = bool(data.get("fork"))
        self.private = bool(data.get("private"))
        self.pushed_at = parse_time(data.get("pushed_at"))

    @property
    def _api(self) -> str:
        return f"/repos/{self.full_name}"

    # Files.
    @cached
    def file(self, path: str, ref: str | None = None) -> str | None:
        params = {"ref": ref or self.default_branch}
        try:
            return self.client.get_text(
                f"{self._api}/contents/{urllib.parse.quote(path)}", params,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except NotFound:
            return None

    def file_url(self, path: str, ref: str | None = None) -> str:
        return f"{self.html_url}/blob/{ref or self.default_branch}/{path}"

    # Releases.
    @cached
    def latest_release(self) -> Release | None:
        try:
            data = self.client.get_json(f"{self._api}/releases/latest")
        except NotFound:
            return None
        assets = [{"name": a["name"], "url": a["browser_download_url"]} for a in data.get("assets", [])]
        return Release(
            tag=data["tag_name"], name=data.get("name") or data["tag_name"], url=data.get("html_url"),
            published_at=parse_time(data.get("published_at")), assets=assets,
        )

    @cached
    def commits_since(self, tag: str) -> int:
        base = urllib.parse.quote(tag, safe="")
        head = urllib.parse.quote(self.default_branch, safe="")
        data = self.client.get_json(f"{self._api}/compare/{base}...{head}")
        return int(data.get("ahead_by", 0))

    def compare_url(self, tag: str) -> str:
        return f"{self.html_url}/compare/{tag}...{self.default_branch}"

    # Issues and pull requests (GitHub returns both from /issues).
    @cached
    def _open_issue_items(self) -> list[dict[str, Any]]:
        return self.client.get_paged(f"{self._api}/issues", {"state": "open", "per_page": 100})

    def open_issues(self) -> list[dict[str, Any]]:
        return [i for i in self._open_issue_items() if "pull_request" not in i]

    def open_pull_requests(self) -> list[dict[str, Any]]:
        return [i for i in self._open_issue_items() if "pull_request" in i]

    def issues_url(self) -> str:
        return f"{self.html_url}/issues"

    def pulls_url(self) -> str:
        return f"{self.html_url}/pulls"

    # CI.
    @cached
    def workflows(self) -> list[Workflow]:
        try:
            data = self.client.get_json(f"{self._api}/actions/workflows", {"per_page": 100})
        except NotFound:
            return []
        return [
            Workflow(id=str(w["id"]), name=w.get("name") or w["path"], path=w["path"], state=w.get("state", "active"))
            for w in data.get("workflows", [])
        ]

    @cached
    def latest_run(self, workflow: Workflow) -> Run | None:
        data = self.client.get_json(
            f"{self._api}/actions/workflows/{workflow.id}/runs",
            {"branch": self.default_branch, "per_page": 10, "exclude_pull_requests": "true"},
        )
        for run in data.get("workflow_runs", []):
            if run.get("status") != "completed":
                continue
            return Run(
                id=str(run["id"]), conclusion=normalise_conclusion(run.get("conclusion")),
                created_at=parse_time(run.get("created_at")), url=run.get("html_url"),
            )
        return None

    @cached
    def run_jobs(self, run: Run) -> list[Job]:
        jobs = self.client.get_paged(
            f"{self._api}/actions/runs/{run.id}/jobs", {"per_page": 100, "filter": "latest"}, item_key="jobs",
        )
        return [Job(name=j.get("name", ""), conclusion=normalise_conclusion(j.get("conclusion"))) for j in jobs]

    # Security.
    @cached
    def security_alerts(self) -> list[SecurityAlert]:
        try:
            alerts = self.client.get_paged(f"{self._api}/dependabot/alerts", {"state": "open", "per_page": 100})
        except (AuthError, NotFound) as err:
            raise NotAvailable(
                "Dependabot alerts are off for this repo, or the token lacks 'Dependabot alerts: read'"
            ) from err
        result = []
        for alert in alerts:
            advisory = alert.get("security_advisory") or {}
            package = ((alert.get("dependency") or {}).get("package") or {}).get("name", "")
            result.append(SecurityAlert(
                severity=(advisory.get("severity") or "low").lower(),
                summary=f"{package}: {advisory.get('summary', '')}".strip(": "),
                url=alert.get("html_url"),
            ))
        return result

    def security_url(self) -> str:
        return f"{self.html_url}/security/dependabot"


class GitHubSource(Source):
    name = "github"

    def __init__(self, cfg: dict[str, Any], client: Client | None = None):
        self.cfg = cfg
        self.client = client or Client(
            cfg.get("github_api", "https://api.github.com"),
            headers={
                "Authorization": f"Bearer {cfg['github_token']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @property
    def api_calls(self) -> int:
        return self.client.calls

    def list_repos(self) -> list[RepoView]:
        try:
            data = self.client.get_paged(
                "/user/repos",
                {"affiliation": "owner,collaborator,organization_member", "per_page": 100, "sort": "full_name"},
            )
        except AuthError as err:
            raise AuthError(err.status, err.url, "GitHub rejected the token (expired or wrong permissions)") from err
        owners = {o.lower() for o in self.cfg.get("github_owners", [])}
        repos = []
        for item in data:
            owner = item.get("owner", {}).get("login", "").lower()
            if owners and owner not in owners:
                continue
            repos.append(GitHubRepo(self.client, item))
        return repos

    def moodle_latest_branch(self) -> int:
        """Highest MOODLE_xxx_STABLE branch in moodle/moodle (e.g. 503 for 5.3)."""
        try:
            refs = self.client.get_json("/repos/moodle/moodle/git/matching-refs/heads/MOODLE_")
        except HttpError:
            return 0
        best = 0
        for ref in refs or []:
            name = ref.get("ref", "").rsplit("/", 1)[-1]
            parts = name.split("_")
            if len(parts) == 3 and parts[2] == "STABLE" and parts[1].isdigit():
                best = max(best, int(parts[1]))
        return best
