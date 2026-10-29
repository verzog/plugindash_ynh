"""Watches for new Moodle releases the plugin doesn't yet cover."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, Finding
from ..moodle import branch_label, branch_name, supported_range
from ._util import ci_text, ci_workflows

ID = "moodle_support"
TITLE = "New Moodle release watch"
DESCRIPTION = "Amber if the newest stable Moodle is outside $plugin->supported, or the CI matrix doesn't test it."
ORDER = 40

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "no $plugin->requires": "Add $plugin->requires to version.php (5.1 is 2025100600).",
    "no $plugin->supported": "Add $plugin->supported = [501, 503]; to version.php.",
    "is out; supported range": "Test on the new Moodle, then raise $plugin->supported, bump the version and release.",
    "CI matrix doesn't test": "Add a cell for that branch to the CI matrix.",
}


def run(repo, plugin, ctx):
    findings = []
    version_url = repo.file_url("version.php")
    if "requires" not in plugin:
        findings.append(Finding(ID, AMBER, "version.php has no $plugin->requires", version_url))
    supported = supported_range(plugin)
    latest = ctx.moodle_latest
    if supported is None:
        findings.append(Finding(ID, AMBER, "version.php has no $plugin->supported range", version_url))
    if latest <= 0:
        findings.append(Finding(ID, INFO, "Couldn't work out the newest stable Moodle branch"))
        return findings
    label = branch_label(latest)
    if supported is not None:
        low, high = supported
        if high < latest:
            findings.append(Finding(
                ID, AMBER, f"Moodle {label} is out; supported range ends at {branch_label(high)}", version_url,
            ))
        else:
            findings.append(Finding(
                ID, OK, f"Supports Moodle {branch_label(low)}–{branch_label(high)}", version_url,
            ))
    workflows = ci_workflows(repo, ctx.cfg)
    if workflows:
        read = [ci_text(repo, wf) for wf in workflows]
        texts = [text for text, _ in read]
        unreadable = any(missing for _, missing in read)  # Its matrix is in a shared workflow we can't see.
        if not unreadable and not any(branch_name(latest) in text for text in texts):
            wf = workflows[0]
            findings.append(Finding(
                ID, AMBER, f"CI matrix doesn't test {branch_name(latest)}", repo.file_url(wf.path),
            ))
    return findings
