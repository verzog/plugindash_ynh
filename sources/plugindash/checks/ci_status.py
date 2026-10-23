"""Is CI passing on the default branch?"""

from __future__ import annotations

import re

from ..model import AMBER, OK, RED, Finding
from ._util import ci_workflows

ID = "ci_status"
TITLE = "CI status"
DESCRIPTION = "Latest CI run on the default branch. Red if it failed; amber if only the Moodle main cell failed."
ORDER = 10

_MAIN_CELL = re.compile(r"(^|[\s(,/])main([\s),/]|$)", re.I)


def is_next_version_cell(job) -> bool:
    """The Moodle `main` matrix cell (allowed to fail), or a GitLab job with allow_failure."""
    return job.allowed_failure or bool(_MAIN_CELL.search(job.name))


def _names(jobs, limit=3) -> str:
    names = [j.name for j in jobs[:limit]]
    more = len(jobs) - limit
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def run(repo, plugin, ctx):
    findings = []
    for wf in ci_workflows(repo, ctx.cfg):
        if wf.state != "active":
            continue
        latest = repo.latest_run(wf)
        if latest is None:
            continue
        if latest.conclusion == "cancelled":
            findings.append(Finding(ID, AMBER, f"Last '{wf.name}' run was cancelled", latest.url))
            continue
        if latest.conclusion not in ("success", "failure"):
            continue
        failed = [j for j in repo.run_jobs(latest) if j.conclusion == "failure"]
        if latest.conclusion == "failure":
            real = [j for j in failed if not is_next_version_cell(j)]
            if failed and not real:
                findings.append(Finding(
                    ID, AMBER, f"'{wf.name}': only the Moodle main cell is failing (allowed to fail; check upstream)",
                    latest.url,
                ))
            else:
                detail = f" ({_names(real)})" if real else ""
                findings.append(Finding(
                    ID, RED, f"'{wf.name}' is failing on {repo.default_branch}{detail}", latest.url,
                ))
        elif failed:
            findings.append(Finding(
                ID, AMBER, f"'{wf.name}' passed, but an allowed-to-fail cell failed ({_names(failed)})", latest.url,
            ))
        else:
            findings.append(Finding(ID, OK, f"'{wf.name}' passing on {repo.default_branch}", latest.url))
    return findings
