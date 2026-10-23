"""Is the Moodle plugins directory listing up to date with the latest release?"""

from __future__ import annotations

import json

from ..http import HttpError
from ..model import AMBER, INFO, OK, Finding
from ..moodle import supported_range
from ._util import version_at

ID = "plugins_directory"
TITLE = "Plugins directory listing"
DESCRIPTION = "Amber if moodle.org's directory offers an older version than your latest release. Unlisted is info only."
ORDER = 70


def run(repo, plugin, ctx):
    if ctx.directory is None:
        return []
    component = plugin.get("component")
    supported = supported_range(plugin)
    branch = supported[1] if supported else ctx.moodle_latest
    if not branch:
        return [Finding(ID, INFO, "No Moodle branch to look the plugin up against")]
    try:
        listing = ctx.directory.lookup(component, branch)
    except (HttpError, ValueError, json.JSONDecodeError) as err:
        return [Finding(ID, INFO, f"Couldn't reach the plugins directory ({err})")]
    if listing is None:
        return [Finding(ID, INFO, "Not listed in the Moodle plugins directory")]
    rel = repo.latest_release()
    released = version_at(repo, rel.tag) if rel else None
    if not released or not isinstance(released.get("version"), int):
        return [Finding(ID, INFO, f"Listed as {listing['release'] or listing['version']}", listing["url"])]
    if listing["version"] < released["version"]:
        return [Finding(
            ID, AMBER, f"Directory has {listing['release'] or listing['version']}; latest release is "
            f"{released.get('release', rel.tag)}. Upload the new zip", listing["url"],
        )]
    return [Finding(ID, OK, f"Directory is up to date ({listing['release'] or listing['version']})", listing["url"])]
