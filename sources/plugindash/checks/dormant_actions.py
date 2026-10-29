"""Is a dormant private repo still spending GitHub Actions minutes on schedules?"""

from __future__ import annotations

import re

from ..model import AMBER, OK, Finding

ID = "dormant_actions"
TITLE = "Dormant repo schedules"
DESCRIPTION = ("Amber if a private GitHub repo with no push for 90 days still has scheduled workflows or "
               "Dependabot, which use up Actions minutes.")
ORDER = 80

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "": "Disable the scheduled workflows in Actions and remove .github/dependabot.yml, or archive the repository.",
}

DORMANT_DAYS = 90


def run(repo, plugin, ctx):
    if repo.source != "github" or not repo.private or repo.pushed_at is None:
        return []  # Public repos don't use minutes; GitLab runners are your own.
    idle = (ctx.now - repo.pushed_at).days
    if idle < DORMANT_DAYS:
        return []
    scheduled = [
        wf.name for wf in repo.workflows()
        if wf.state == "active" and re.search(r"^\s*-?\s*cron\s*:", repo.workflow_text(wf) or "", re.M)
    ]
    if repo.file(".github/dependabot.yml") is not None or repo.file(".github/dependabot.yaml") is not None:
        scheduled.append("Dependabot")
    if scheduled:
        return [Finding(
            ID, AMBER, f"No push for {idle} days, but {', '.join(scheduled)} still run on a schedule; "
            "disable them to save Actions minutes", f"{repo.html_url}/actions",
        )]
    return [Finding(ID, OK, f"No push for {idle} days and nothing scheduled")]
