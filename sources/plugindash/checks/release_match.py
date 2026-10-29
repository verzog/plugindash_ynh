"""Does the latest release tag agree with version.php?"""

from __future__ import annotations

from ..http import HttpError
from ..model import INFO, OK, RED, Finding
from ..moodle import normalise_tag, release_text
from ._util import version_at

ID = "release_match"
TITLE = "Release matches version.php"
DESCRIPTION = ("Red if the latest tag (minus its 'v') differs from $plugin->release at that tag, main goes "
               "backwards, or the latest release didn't raise $plugin->version (so Moodle won't upgrade).")
ORDER = 20

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "has no version.php": "Tag a commit that contains version.php.",
    "expects $plugin->release": "Set $plugin->release to match the tag, merge, then publish a new release.",
    "is older than in": "Raise $plugin->version on the default branch above the released one.",
    "won't offer the upgrade": "Raise $plugin->version above the previous release's and publish a new release.",
}


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        # Info, not amber: an unreleased plugin isn't unhealthy, and this fired on ~20 repos.
        return [Finding(ID, INFO, "No published releases yet", f"{repo.html_url}/releases")]
    findings = []
    tagged = version_at(repo, rel.tag)
    tag_release = normalise_tag(rel.tag)
    if tagged is None:
        findings.append(Finding(ID, RED, f"Release {rel.tag} has no version.php", rel.url))
        return findings
    at_tag = release_text(tagged.get("release"))
    if at_tag != tag_release:
        # Show the normalised tag (its 'v' stripped) so a stray 'v' or a "(Build …)"
        # suffix in $plugin->release is visible, not a baffling "v1.3.0 != 'v1.3.0'".
        findings.append(Finding(
            ID, RED,
            f"Tag {rel.tag} expects $plugin->release '{tag_release}', "
            f"but it's '{at_tag or 'missing'}' in that release",
            rel.url,
        ))
    else:
        findings.append(Finding(ID, OK, f"Tag {rel.tag} matches $plugin->release", rel.url))
    main_version, tag_version = plugin.get("version"), tagged.get("version")
    if isinstance(main_version, int) and isinstance(tag_version, int) and main_version < tag_version:
        findings.append(Finding(
            ID, RED, f"$plugin->version on {repo.default_branch} ({main_version}) is older than in {rel.tag} "
            f"({tag_version})", repo.file_url("version.php"),
        ))
    try:
        previous = repo.previous_release()
        before = version_at(repo, previous.tag) if previous else None
    except HttpError as err:
        # Keep the findings above: a failed look-back mustn't hide a mismatch already found.
        findings.append(Finding(ID, INFO, f"Couldn't compare with the previous release ({err})"))
        return findings
    before_version = before.get("version") if before else None
    if isinstance(tag_version, int) and isinstance(before_version, int) and tag_version <= before_version:
        findings.append(Finding(
            ID, RED, f"{rel.tag} has $plugin->version {tag_version}, not higher than {previous.tag} "
            f"({before_version}), so Moodle won't offer the upgrade", rel.url,
        ))
    return findings
