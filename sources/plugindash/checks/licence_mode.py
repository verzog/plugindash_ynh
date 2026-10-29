"""Which licence mode the plugin is in, and the rule that follows from it: in-house stays private."""

from __future__ import annotations

from ..model import INFO, OK, RED, Finding
from ..modes import MODE_A, MODE_B, plugin_mode

ID = "licence_mode"
TITLE = "Licence mode"
DESCRIPTION = "Red if an in-house SCCA (Mode A) plugin is in a public repository. Shows each plugin's mode."
ORDER = 49

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "": "Make the repository private (Settings, General, Danger Zone).",
}


def run(repo, plugin, ctx):
    mode = plugin_mode(plugin)
    if mode == MODE_A:
        if not repo.private:
            return [Finding(ID, RED, "In-house SCCA plugin is in a public repository; make it private", repo.html_url)]
        return [Finding(ID, OK, "In-house SCCA plugin (Mode A) in a private repository")]
    if mode == MODE_B:
        return [Finding(ID, OK, "GPL plugin (Mode B)")]
    return [Finding(ID, INFO, f"Licence mode not recognised (@license: {plugin.get('license') or 'none'})")]
