"""Do the repository's own files match the plugin's licence mode and the Moodle plugin conventions?"""

from __future__ import annotations

import re

from ..model import AMBER, OK, RED, Finding
from ..modes import MODE_A, MODE_B, plugin_mode

ID = "repo_files"
TITLE = "Repository files"
DESCRIPTION = ("Red if an in-house SCCA plugin doesn't exclude phpcs's GPL boilerplate sniff (CI fails). Amber if a "
               "GPL plugin excludes it, the @copyright holder doesn't match the licence mode, .gitattributes is "
               "missing eol=lf or export-ignore lines, or there's no Privacy API provider.")
ORDER = 51

BOILERPLATE_SNIFF = "moodle.Files.BoilerplateComment"
PHPCS_FILES = (".phpcs.xml", "phpcs.xml")
_COPYRIGHT = re.compile(r"@copyright\s+(.+)")


def _excludes_sniff(repo, version_text: str) -> bool:
    """True if phpcs's boilerplate sniff is turned off, in .phpcs.xml or in version.php itself."""
    if re.search(rf"phpcs:disable\s+{re.escape(BOILERPLATE_SNIFF)}", version_text):
        return True
    for name in PHPCS_FILES:
        text = repo.file(name)
        if text and re.search(rf'<exclude\s+name="{re.escape(BOILERPLATE_SNIFF)}"', text):
            return True
    return False


def _copyright_finding(repo, plugin, mode, version_text, version_url):
    match = _COPYRIGHT.search(version_text)
    holder = match.group(1).strip() if match else ""
    if not holder or repo.fork:  # Forks keep the original author's copyright.
        return None
    scca = "skin cancer college" in holder.lower()
    if mode == MODE_A and not scca:
        return Finding(ID, AMBER, f"@copyright is '{holder}'; an SCCA plugin uses '© Skin Cancer College Australasia'",
                       version_url)
    if mode == MODE_B and (scca or "vernon spain" not in holder.lower()):
        return Finding(ID, AMBER, f"@copyright is '{holder}'; a GPL plugin uses 'Vernon Spain' (or 'Vernon Spain "
                       "trading as EduCheckout')", version_url)
    return None


def run(repo, plugin, ctx):
    mode = plugin_mode(plugin)
    version_text = repo.file("version.php") or ""
    version_url = repo.file_url("version.php")
    findings = []
    excluded = _excludes_sniff(repo, version_text)
    if mode == MODE_A and not excluded:
        findings.append(Finding(
            ID, RED, f"phpcs will fail on the proprietary header: exclude {BOILERPLATE_SNIFF} in .phpcs.xml",
            repo.html_url,
        ))
    elif mode == MODE_B and excluded:
        findings.append(Finding(
            ID, AMBER, f"A GPL plugin should keep the {BOILERPLATE_SNIFF} sniff; remove the exclusion", repo.html_url,
        ))
    copyright_finding = _copyright_finding(repo, plugin, mode, version_text, version_url)
    if copyright_finding:
        findings.append(copyright_finding)
    attributes = repo.file(".gitattributes")
    if attributes is None:
        findings.append(Finding(ID, AMBER, "No .gitattributes (line endings and export-ignore)", repo.html_url))
    else:
        missing = []
        if not re.search(r"eol\s*=\s*lf", attributes):
            missing.append("* text=auto eol=lf")
        if mode != MODE_A:  # Only distributed plugins build release zips.
            for path in ("/.github", "/tests"):
                if not re.search(rf"^{re.escape(path)}/?\s+export-ignore", attributes, re.M):
                    missing.append(f"{path} export-ignore")
        if missing:
            findings.append(Finding(
                ID, AMBER, f".gitattributes is missing: {', '.join(missing)}", repo.file_url(".gitattributes"),
            ))
    if repo.file("classes/privacy/provider.php") is None:
        findings.append(Finding(ID, AMBER, "No Privacy API provider (classes/privacy/provider.php)", repo.html_url))
    if not findings:
        findings.append(Finding(ID, OK, "Repository files match the conventions"))
    return findings
