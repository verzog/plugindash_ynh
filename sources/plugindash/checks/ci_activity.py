"""Catches CI that has gone quiet: no workflow, disabled by GitHub, or not run lately."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, Finding
from ._util import ci_workflows

ID = "ci_activity"
TITLE = "Silent CI"
DESCRIPTION = "Amber if there's no CI, GitHub has disabled a workflow, or CI hasn't run within the stale-days limit."
ORDER = 11

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "GitHub disabled": "In Actions, open the workflow and choose Enable workflow, then push a commit to run it.",
    "never finished": "Check Actions for runs that are stuck queued or fail before they start.",
    "Last CI run": "Re-run the workflow (or push a small change) to confirm CI still passes.",
}


def run(repo, plugin, ctx):
    workflows = ci_workflows(repo, ctx.cfg)
    actions_url = f"{repo.html_url}/actions" if repo.source == "github" else f"{repo.html_url}/-/pipelines"
    if not workflows:
        # The fix depends on where the repo lives, so it's set here rather than in FIX.
        fix = (".github/workflows/moodle-ci.yml, based on moodle-plugin-ci's gha.dist.yml" if repo.source == "github"
               else ".gitlab-ci.yml running moodle-plugin-ci")
        return [Finding(ID, AMBER, "No CI workflow found", actions_url, fix=f"Add {fix}.")]
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
