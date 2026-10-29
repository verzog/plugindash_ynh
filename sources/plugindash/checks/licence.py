"""Does the declared licence agree across version.php, LICENSE and README?"""

from __future__ import annotations

import re

from ..model import AMBER, INFO, OK, RED, Finding

ID = "licence"
TITLE = "Licence consistency"
DESCRIPTION = "Red if the @license tag and the LICENSE file disagree; amber if the README disagrees or files are missing."
ORDER = 50

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "no @license tag": "Add the @license line for the plugin's licence mode to version.php's docblock.",
    "No LICENSE file": "Add a LICENSE file with the full text of the declared licence.",
    "but @license says": "Make the file match the @license tag (or correct the tag).",
    "No README": "Add a README with a Licence section.",
    "no licence section": "Add a Licence section to the README naming the licence.",
}

LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE", "LICENCE.md")

LABELS = {
    "gpl3": "GPLv3", "gpl2": "GPLv2", "agpl": "AGPL", "lgpl": "LGPL", "mit": "MIT", "apache": "Apache",
    "bsd": "BSD", "proprietary": "proprietary", "unknown": "unrecognised",
}


def classify_declared(tag: str) -> str:
    text = tag.lower()
    if "proprietary" in text or "all rights reserved" in text:
        return "proprietary"
    if "affero" in text or "agpl" in text:
        return "agpl"
    if "gpl" in text or "general public license" in text:
        return "gpl3" if ("v3" in text or "3" in text or "copyleft/gpl" in text) else "gpl2"
    if "mit" in re.findall(r"[a-z]+", text):
        return "mit"
    if "apache" in text:
        return "apache"
    return "unknown"


def classify_text(text: str) -> str:
    head = "\n".join(text.splitlines()[:40]).lower()
    if "affero general public license" in head:
        return "agpl"
    if "lesser general public license" in head:
        return "lgpl"
    if "gnu general public license" in head:
        return "gpl3" if "version 3" in head else ("gpl2" if "version 2" in head else "gpl3")
    if "mit license" in head or "permission is hereby granted, free of charge" in head:
        return "mit"
    if "apache license" in head:
        return "apache"
    if "redistribution and use in source and binary forms" in head:
        return "bsd"
    if "proprietary" in head or "all rights reserved" in head or "not free software" in head:
        return "proprietary"
    return "unknown"


def readme_licence(readme: str) -> str | None:
    """Classify the README's licence section (or, failing that, the whole README)."""
    match = re.search(r"^#{1,6}\s*licen[cs]e.*?$(.*?)(?=^#{1,6}\s|\Z)", readme, re.I | re.M | re.S)
    section = match.group(1) if match else ""
    if not section.strip():
        return None
    lowered = section.lower()
    if "proprietary" in lowered or "all rights reserved" in lowered:
        return "proprietary"
    if "affero" in lowered or "agpl" in lowered:
        return "agpl"
    if "gpl" in lowered or "general public license" in lowered:
        return "gpl3" if ("3" in lowered or "gpl-3" in lowered) else "gpl2"
    if re.search(r"\bmit\b", lowered):
        return "mit"
    if "apache" in lowered:
        return "apache"
    return "unknown"


def _family(kind: str) -> str:
    return "gpl" if kind in ("gpl3", "gpl2") else kind


def run(repo, plugin, ctx):
    findings = []
    tag = plugin.get("license")
    version_url = repo.file_url("version.php")
    if not tag:
        return [Finding(ID, AMBER, "version.php has no @license tag", version_url)]
    declared = classify_declared(tag)
    if declared == "unknown":
        findings.append(Finding(ID, INFO, f"Couldn't classify @license '{tag}'", version_url))
        return findings

    licence_text, licence_name = None, None
    for name in LICENCE_FILES:
        licence_text = repo.file(name)
        if licence_text is not None:
            licence_name = name
            break
    if licence_text is None:
        findings.append(Finding(ID, AMBER, f"No LICENSE file (declared: {LABELS[declared]})", repo.html_url))
    else:
        actual = classify_text(licence_text)
        url = repo.file_url(licence_name)
        if actual == "unknown":
            findings.append(Finding(ID, INFO, f"{licence_name} text not recognised; check it by hand", url))
        elif actual == declared:
            findings.append(Finding(ID, OK, f"{licence_name} matches @license ({LABELS[declared]})", url))
        elif _family(actual) == _family(declared):
            findings.append(Finding(
                ID, AMBER, f"{licence_name} is {LABELS[actual]} text but @license says {LABELS[declared]}", url,
            ))
        else:
            findings.append(Finding(
                ID, RED, f"{licence_name} is {LABELS[actual]} but @license says {LABELS[declared]}", url,
            ))

    readme = repo.readme()
    if readme is None:
        findings.append(Finding(ID, AMBER, "No README", repo.html_url))
    else:
        stated = readme_licence(readme)
        if stated is None:
            findings.append(Finding(ID, AMBER, "README has no licence section", repo.html_url))
        elif stated != "unknown" and _family(stated) != _family(declared):
            findings.append(Finding(
                ID, AMBER, f"README says {LABELS[stated]} but @license says {LABELS[declared]}", repo.html_url,
            ))
    return findings
