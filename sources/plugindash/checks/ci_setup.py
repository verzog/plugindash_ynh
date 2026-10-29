"""Does the CI workflow follow the Moodle plugin CI conventions?"""

from __future__ import annotations

import os
import re

from ..model import AMBER, OK, RED, Finding
from ..modes import MODE_A, plugin_mode
from ..moodle import branch_label, branch_name, min_php
from ._ci import branch_number, command_lines, has_flag, matrix_cells, php_version, strip_comments
from ._util import ci_workflows

ID = "ci_setup"
TITLE = "CI setup"
DESCRIPTION = ("Amber if the CI workflow strays from the conventions (branch-aware matrix, a main cell allowed "
               "to fail, TZ Australia/Sydney, warnings as failures, grunt on the lowest branch only). Red if a "
               "matrix cell runs a PHP version that Moodle branch can't install on.")
ORDER = 12

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "below the": "Remove that branch's cells from the CI matrix.",
    "matrix doesn't test": "Add a cell for that branch to the CI matrix.",
    "No Moodle main cell": "Add {moodle-branch: 'main', php: '8.4', database: 'pgsql'} to the CI matrix.",
    "isn't allowed to fail": "Add continue-on-error: ${{ matrix.moodle-branch == 'main' }} to the test job.",
    "won't install": "Use PHP 8.3 or later for Moodle 5.2+ cells (PHP 8.2 only on 5.1).",
    "TZ": "Set TZ: Australia/Sydney in the CI config (under env: on GitHub, variables: on GitLab).",
    "Warnings don't fail": "Add the listed flags to those moodle-plugin-ci steps.",
    "Grunt runs": "Add an if: so the Grunt step only runs on the lowest supported branch.",
    ".travis.yml": "Delete .travis.yml.",
    "No release workflow": "Add .github/workflows/release.yml (the 'Release zip' workflow).",
}

# moodle-plugin-ci commands and the flag that makes warnings fail CI.
STRICT_FLAGS = (
    ("phpcs", "--max-warnings 0"),
    ("phpdoc", "--max-warnings 0"),
    ("phpunit", "--fail-on-warning"),
    ("grunt", "--max-lint-warnings 0"),
    ("behat", "--auto-rerun"),
)


def _plugin_ci(repo, cfg):
    """The first CI workflow that runs moodle-plugin-ci or has a Moodle branch matrix."""
    for wf in ci_workflows(repo, cfg):
        text = repo.workflow_text(wf) or ""
        if "moodle-plugin-ci" in text or re.search(r"moodle[-_]branch", text, re.I):
            return wf, text
    return None, ""


def _matrix_findings(text, low, high, latest, url):
    findings = []
    cells, uncertain = matrix_cells(text)
    branches = {branch_number(c["branch"]) for c in cells}
    old = sorted(b for b in branches if isinstance(b, int) and b < low)
    if old:
        labels = ", ".join(branch_label(b) for b in old)
        findings.append(Finding(
            ID, AMBER, f"CI still tests Moodle {labels}, below the {branch_label(low)} baseline", url,
        ))
    for branch in sorted({low, high}):
        # The newest stable branch is already covered by the moodle_support check.
        if branch not in branches and branch != latest:
            findings.append(Finding(ID, AMBER, f"CI matrix doesn't test {branch_name(branch)}", url))
    if "main" not in branches:
        findings.append(Finding(ID, AMBER, "No Moodle main cell in the CI matrix (keep one, allowed to fail)", url))
    elif not re.search(r"continue-on-error\s*:.*main", text):
        findings.append(Finding(
            ID, AMBER, "The Moodle main cell isn't allowed to fail; add continue-on-error for it", url,
        ))
    if not uncertain:
        bad = []
        for cell in cells:
            branch, php = branch_number(cell["branch"]), php_version(cell["php"])
            if isinstance(branch, int) and php and php < min_php(branch):
                bad.append(f"Moodle {branch_label(branch)} on PHP {php[0]}.{php[1]}")
        if bad:
            findings.append(Finding(
                ID, RED, f"CI runs {', '.join(sorted(set(bad)))}, which won't install; drop or update that cell", url,
            ))
    return findings


def _grunt_on_other_branches(text, low):
    """True if a grunt step isn't limited to the lowest branch by an `if:` just above it."""
    lines = text.splitlines()
    for number, _ in command_lines(text, "grunt"):
        nearby = "\n".join(lines[max(0, number - 6):number + 1])
        if branch_name(low) not in nearby:
            return True
    return False


def run(repo, plugin, ctx):
    wf, raw = _plugin_ci(repo, ctx.cfg)
    if wf is None:
        return []  # No CI at all is the ci_activity check's job.
    text = strip_comments(raw)
    url = repo.file_url(wf.path)
    low, high = ctx.cfg["moodle_min_branch"], ctx.cfg["moodle_max_branch"]
    github = repo.source == "github"
    findings = []
    if github:  # GitLab's parallel: matrix uses a different layout; only the common rules apply there.
        findings += _matrix_findings(text, low, high, ctx.moodle_latest, url)
    tz = re.search(r"\bTZ\s*:\s*['\"]?([\w/+-]+)", text)
    if not tz:
        findings.append(Finding(ID, AMBER, "CI doesn't set TZ: Australia/Sydney (DST bugs only show in Sydney)", url))
    elif tz.group(1) != "Australia/Sydney":
        findings.append(Finding(ID, AMBER, f"CI sets TZ {tz.group(1)}; use Australia/Sydney so DST bugs show", url))
    missing = []
    for command, flag in STRICT_FLAGS:
        lines = [line for _, line in command_lines(text, command)]
        if lines and not any(has_flag(line, flag) for line in lines):
            missing.append(f"{command} {flag}")
    if missing:
        findings.append(Finding(ID, AMBER, f"Warnings don't fail CI; add {', '.join(missing)}", url))
    if github and _grunt_on_other_branches(text, low):
        findings.append(Finding(ID, AMBER, f"Grunt runs on every branch; limit it to {branch_name(low)}", url))
    if github and repo.file(".travis.yml") is not None:
        findings.append(Finding(
            ID, AMBER, "Remove .travis.yml; CI runs on GitHub Actions", repo.file_url(".travis.yml"),
        ))
    if github and plugin_mode(plugin) != MODE_A and not any(
        os.path.basename(w.path).lower() in ("release.yml", "release.yaml") for w in repo.workflows()
    ):
        findings.append(Finding(
            ID, AMBER, "No release workflow (.github/workflows/release.yml) to build the install zip", url,
        ))
    if not findings:
        findings.append(Finding(ID, OK, "CI setup follows the conventions", url))
    return findings
