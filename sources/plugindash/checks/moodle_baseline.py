"""Is the plugin held to the supported Moodle range set in the config panel (5.1 to 5.3 by default)?"""

from __future__ import annotations

from ..model import AMBER, OK, Finding
from ..moodle import BRANCH_VERSIONS, branch_label, supported_range

ID = "moodle_baseline"
TITLE = "Moodle baseline"
DESCRIPTION = ("Amber if version.php requires or supports a Moodle older than the lowest supported branch, "
               "or $plugin->release has a leading 'v'.")
ORDER = 41

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "requires is": "Set $plugin->requires to the lowest supported branch (5.1 is 2025100600).",
    "supported starts": "Raise the lower bound of $plugin->supported to the lowest supported branch.",
    "tag carries": "Remove the 'v' from $plugin->release.",
}


def run(repo, plugin, ctx):
    low = ctx.cfg["moodle_min_branch"]
    high = ctx.cfg["moodle_max_branch"]
    version_url = repo.file_url("version.php")
    findings = []
    requires = plugin.get("requires")
    floor = BRANCH_VERSIONS.get(low)
    if isinstance(requires, int) and floor and requires < floor:
        findings.append(Finding(
            ID, AMBER, f"$plugin->requires is {requires}, older than Moodle {branch_label(low)} ({floor})", version_url,
        ))
    supported = supported_range(plugin)
    if supported and supported[0] < low:
        findings.append(Finding(
            ID, AMBER, f"$plugin->supported starts at {branch_label(supported[0])}, below the "
            f"{branch_label(low)} baseline", version_url,
        ))
    release = str(plugin.get("release") or "")
    if release[:1] in ("v", "V") and release[1:2].isdigit():
        findings.append(Finding(
            ID, AMBER, f"$plugin->release is '{release}'; the tag carries the 'v', version.php doesn't", version_url,
        ))
    if not findings:
        findings.append(Finding(ID, OK, f"Meets the Moodle {branch_label(low)}–{branch_label(high)} baseline"))
    return findings
