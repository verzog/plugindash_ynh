"""Does the latest release tag agree with version.php?"""

from __future__ import annotations

from ..model import AMBER, OK, RED, Finding
from ..moodle import normalise_tag, release_text
from ._util import version_at

ID = "release_match"
TITLE = "Release matches version.php"
DESCRIPTION = "Red if the latest tag (minus its 'v') differs from $plugin->release at that tag, or main goes backwards."
ORDER = 20


def run(repo, plugin, ctx):
    rel = repo.latest_release()
    if rel is None:
        return [Finding(ID, AMBER, "No published releases yet", f"{repo.html_url}/releases")]
    findings = []
    tagged = version_at(repo, rel.tag)
    tag_release = normalise_tag(rel.tag)
    if tagged is None:
        findings.append(Finding(ID, RED, f"Release {rel.tag} has no version.php", rel.url))
        return findings
    at_tag = release_text(tagged.get("release"))
    if at_tag != tag_release:
        findings.append(Finding(
            ID, RED, f"Tag {rel.tag} doesn't match $plugin->release '{at_tag or 'missing'}' in that release",
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
    return findings
