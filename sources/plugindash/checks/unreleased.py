"""Work merged to the default branch but not yet released."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, Finding
from ..modes import MODE_A, plugin_mode
from ..moodle import normalise_tag, release_text, version_key
from ._util import plural

ID = "unreleased"
TITLE = "Unreleased changes"
DESCRIPTION = ("Amber when the default branch has commits that aren't in the latest release, or version.php "
               "already names a newer release that hasn't been published (info for SCCA plugins).")
ORDER = 22

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "publish v": "Publish it: create a GitHub release with that tag (the zip builds itself).",
    "not yet released": "When it's ready, bump version.php and publish a release.",
}


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return []
    count = repo.commits_since(rel.tag)
    if count == 0:
        return [Finding(ID, OK, f"Nothing unreleased since {rel.tag}", rel.url)]
    # In-house (Mode A) plugins may be deployed straight from git, so unreleased work is only a note.
    level = INFO if plugin_mode(plugin) == MODE_A else AMBER
    bumped = release_text(plugin.get("release"))
    released = normalise_tag(rel.tag)
    if bumped and bumped != released and version_key(bumped) > version_key(released):
        # version.php was bumped for the next release, which is the clearer thing to say.
        return [Finding(
            ID, level, f"version.php says {bumped} but the latest release is {rel.tag}; publish v{bumped} "
            f"({plural(count, 'commit')} waiting)", repo.compare_url(rel.tag),
        )]
    return [Finding(
        ID, level, f"{plural(count, 'commit')} on {repo.default_branch} since {rel.tag}, not yet released",
        repo.compare_url(rel.tag),
    )]
