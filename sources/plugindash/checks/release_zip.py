"""Is the installable zip attached to the latest release?"""

from __future__ import annotations

from ..model import AMBER, INFO, OK, RED, Finding
from ..modes import MODE_A, plugin_mode

ID = "release_zip"
TITLE = "Release zip attached"
DESCRIPTION = ("Red if the latest release has no .zip; amber if it isn't named <component>-<tag>.zip. "
               "Info only for in-house SCCA plugins.")
ORDER = 21

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "no zip attached": "Re-run the release workflow's run for that tag (don't attach zips by hand).",
    "Zip is named": "Fix the release workflow so it builds <component>-<tag>.zip.",
}


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return []
    zips = [a for a in rel.assets if a.get("name", "").lower().endswith(".zip")]
    # In-house (Mode A) plugins are never distributed, so a missing or oddly named zip is only a note.
    in_house = plugin_mode(plugin) == MODE_A
    if not zips:
        if in_house:
            return [Finding(ID, INFO, f"Release {rel.tag} has no zip (not needed for in-house plugins)", rel.url)]
        return [Finding(ID, RED, f"Release {rel.tag} has no zip attached; re-run the release workflow", rel.url)]
    expected = f"{plugin.get('component')}-{rel.tag}.zip"
    if any(a["name"] == expected for a in zips):
        return [Finding(ID, OK, f"{expected} attached", rel.url)]
    return [Finding(ID, INFO if in_house else AMBER, f"Zip is named {zips[0]['name']}; expected {expected}", rel.url)]
