"""Open Dependabot security alerts."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, RED, Finding, NotAvailable
from ._util import plural

ID = "security_alerts"
TITLE = "Security alerts"
DESCRIPTION = "Red for open critical/high Dependabot alerts; amber for medium/low."
ORDER = 60

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "critical/high": "Update the affected dependency now (Security, Dependabot).",
    "medium/low": "Update the dependency, or dismiss the alert with a reason.",
}


def run(repo, plugin, ctx):
    try:
        alerts = repo.security_alerts()
    except NotAvailable as err:
        return [Finding(ID, INFO, str(err))]
    if not alerts:
        return [Finding(ID, OK, "No open security alerts", repo.security_url())]
    serious = [a for a in alerts if a.severity in ("critical", "high")]
    if serious:
        return [Finding(
            ID, RED, f"{plural(len(serious), 'critical/high security alert')} open "
            f"({len(alerts)} in total)", repo.security_url(),
        )]
    return [Finding(ID, AMBER, f"{plural(len(alerts), 'open security alert')} (medium/low)", repo.security_url())]
