"""Open issues and pull requests."""

from __future__ import annotations

from ..model import AMBER, OK, Finding
from ._util import plural

ID = "issues"
TITLE = "Open issues and pull requests"
DESCRIPTION = "Amber while any issue or pull request is open."
ORDER = 30


def run(repo, plugin, ctx):
    findings = []
    issues = repo.open_issues()
    pulls = repo.open_pull_requests()
    word = "merge request" if repo.source == "gitlab" else "pull request"
    if issues:
        findings.append(Finding(ID, AMBER, f"{plural(len(issues), 'open issue')}", repo.issues_url()))
    if pulls:
        findings.append(Finding(ID, AMBER, f"{plural(len(pulls), 'open ' + word)}", repo.pulls_url()))
    if not findings:
        findings.append(Finding(ID, OK, f"No open issues or {word}s", repo.issues_url()))
    return findings
