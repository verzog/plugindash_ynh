"""Work merged to the default branch but not yet released."""

from __future__ import annotations

from ..model import AMBER, OK, Finding
from ._util import plural

ID = "unreleased"
TITLE = "Unreleased changes"
DESCRIPTION = "Amber when the default branch has commits that aren't in the latest release."
ORDER = 22


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return []
    count = repo.commits_since(rel.tag)
    if count == 0:
        return [Finding(ID, OK, f"Nothing unreleased since {rel.tag}", rel.url)]
    return [Finding(
        ID, AMBER, f"{plural(count, 'commit')} on {repo.default_branch} since {rel.tag}, not yet released",
        repo.compare_url(rel.tag),
    )]
