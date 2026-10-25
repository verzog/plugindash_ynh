"""Work merged to the default branch but not yet released."""

from __future__ import annotations

from ..model import AMBER, INFO, OK, Finding
from ..modes import MODE_A, plugin_mode
from ._util import plural

ID = "unreleased"
TITLE = "Unreleased changes"
DESCRIPTION = "Amber when the default branch has commits that aren't in the latest release (info for SCCA plugins)."
ORDER = 22


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return []
    count = repo.commits_since(rel.tag)
    if count == 0:
        return [Finding(ID, OK, f"Nothing unreleased since {rel.tag}", rel.url)]
    # In-house (Mode A) plugins may be deployed straight from git, so unreleased work is only a note.
    level = INFO if plugin_mode(plugin) == MODE_A else AMBER
    return [Finding(
        ID, level, f"{plural(count, 'commit')} on {repo.default_branch} since {rel.tag}, not yet released",
        repo.compare_url(rel.tag),
    )]
