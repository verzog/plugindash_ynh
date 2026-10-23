"""Is the installable zip attached to the latest release?"""

from __future__ import annotations

from ..model import AMBER, OK, RED, Finding

ID = "release_zip"
TITLE = "Release zip attached"
DESCRIPTION = "Red if the latest release has no .zip; amber if it isn't named <component>-<tag>.zip."
ORDER = 21


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return []
    zips = [a for a in rel.assets if a.get("name", "").lower().endswith(".zip")]
    if not zips:
        return [Finding(ID, RED, f"Release {rel.tag} has no zip attached; re-run the release workflow", rel.url)]
    expected = f"{plugin.get('component')}-{rel.tag}.zip"
    if any(a["name"] == expected for a in zips):
        return [Finding(ID, OK, f"{expected} attached", rel.url)]
    return [Finding(ID, AMBER, f"Zip is named {zips[0]['name']}; expected {expected}", rel.url)]
