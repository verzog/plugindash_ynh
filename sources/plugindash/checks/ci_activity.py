"""Catches CI that has gone quiet: no workflow, disabled by GitHub, or not run lately."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, Finding
from ._util import ci_workflows

ID = "ci_activity"
TITLE = "Silent CI"
DESCRIPTION = "Amber if there's no CI, GitHub has disabled a workflow, or CI hasn't run within the stale-days limit."
ORDER = 11


def run(repo, plugin, ctx):
    workflows = ci_workflows(repo, ctx.cfg)
    actions_url = f"{repo.html_url}/actions" if repo.source == "github" else f"{repo.html_url}/-/pipelines"
    if not workflows:
        return [Finding(ID, AMBER, "No CI workflow found", actions_url)]
    findings = []
    newest = None
    for wf in workflows:
        if wf.state == "disabled_inactivity":
            findings.append(Finding(
                ID, AMBER, f"GitHub disabled '{wf.name}' after 60 days without activity; re-enable it in Actions",
                actions_url,
            ))
            continue
        if wf.state.startswith("disabled"):
            findings.append(Finding(ID, INFO, f"'{wf.name}' is disabled", actions_url))
            continue
        latest = repo.latest_run(wf)
        if latest and (newest is None or latest.created_at > newest.created_at):
            newest = latest
    if newest is None:
        if not any(f.level == AMBER for f in findings):
            findings.append(Finding(ID, AMBER, f"CI has never finished a run on {repo.default_branch}", actions_url))
        return findings
    age = (ctx.now - newest.created_at).days
    if age > ctx.cfg["stale_days"]:
        findings.append(Finding(ID, AMBER, f"Last CI run was {age} days ago", newest.url))
    else:
        findings.append(Finding(ID, OK, f"CI ran {age} day{'s' if age != 1 else ''} ago", newest.url))
    return findings
