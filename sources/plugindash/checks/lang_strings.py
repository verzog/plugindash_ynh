"""Is the plugin's English language file sorted, and written in Australian English?"""

from __future__ import annotations

import re

from ..model import AMBER, OK, Finding

ID = "lang_strings"
TITLE = "Language strings"
DESCRIPTION = ("Amber if lang/en has no language file, its keys aren't in LC_ALL=C order (or repeat), or its strings "
               "use US spellings (color, customize, behavior, enrollment...).")
ORDER = 52

_KEY = re.compile(r"""^\$string\[\s*(['"])(.+?)\1\s*\]\s*=\s*(.*)$""", re.M)

# US spelling -> Australian spelling. Whole words only; -ize stems are listed one by one, because plenty of
# words merely end in "ize" ("size", "prize"). "license" is left out: it's correct in AU English as a verb.
US_WORDS = {
    "color": "colour", "colors": "colours", "colored": "coloured", "coloring": "colouring",
    "behavior": "behaviour", "behaviors": "behaviours", "favorite": "favourite", "favorites": "favourites",
    "center": "centre", "centered": "centred", "enrollment": "enrolment", "enrollments": "enrolments",
    "enroll": "enrol", "canceled": "cancelled", "canceling": "cancelling", "labeled": "labelled",
    "labeling": "labelling", "catalog": "catalogue", "analyze": "analyse", "analyzed": "analysed",
}
IZE_STEMS = (
    "customiz", "organiz", "recogniz", "prioritiz", "optimiz", "summariz", "minimiz", "maximiz", "authoriz",
    "initializ", "finaliz", "synchroniz", "normaliz", "categoriz", "visualiz", "personaliz", "specializ",
    "standardiz", "utiliz", "emphasiz", "realiz", "memoriz", "characteriz", "serializ",
)
_IZE = re.compile(r"\b(" + "|".join(IZE_STEMS) + r")(e|es|ed|ing|ation|ations|er|ers)\b", re.I)
_WORD = re.compile(r"\b(" + "|".join(sorted(US_WORDS, key=len, reverse=True)) + r")\b", re.I)


def lang_file(component: str) -> str:
    """Activity modules drop the 'mod_' prefix: mod_forum -> lang/en/forum.php."""
    name = component[4:] if component.startswith("mod_") else component
    return f"lang/en/{name}.php"


def _prose(value: str) -> str:
    """The readable text of a string's value: placeholders, HTML tags and PHP concatenation removed."""
    text = re.sub(r"\{[^}]*\}", " ", value)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\$[A-Za-z_][\w>-]*", " ", text)


def us_spellings(values: list[str]) -> dict[str, str]:
    """US words found -> their Australian spelling."""
    found: dict[str, str] = {}
    for value in values:
        prose = _prose(value)
        for match in _WORD.finditer(prose):
            word = match.group(1).lower()
            found.setdefault(word, US_WORDS[word])
        for match in _IZE.finditer(prose):
            word = match.group(0).lower()
            found.setdefault(word, match.group(1).lower()[:-1] + "s" + match.group(2).lower())
    return found


def run(repo, plugin, ctx):
    component = plugin.get("component") or ""
    path = lang_file(component)
    text = repo.file(path)
    if text is None:
        return [Finding(ID, AMBER, f"No language file ({path})", repo.html_url)]
    url = repo.file_url(path)
    entries = _KEY.findall(text)
    keys = [key for _, key, _ in entries]
    findings = []
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        findings.append(Finding(ID, AMBER, f"Repeated language string keys: {', '.join(duplicates[:5])}", url))
    # Python compares strings by code point, which for these ASCII keys is LC_ALL=C byte order.
    for previous, key in zip(keys, keys[1:]):
        if key < previous:
            findings.append(Finding(
                ID, AMBER, f"Language strings aren't in LC_ALL=C order: '{key}' comes after '{previous}'", url,
            ))
            break
    spellings = us_spellings([value for _, _, value in entries])
    if spellings:
        shown = [f"{us} ({au})" for us, au in sorted(spellings.items())[:5]]
        more = f" and {len(spellings) - 5} more" if len(spellings) > 5 else ""
        findings.append(Finding(ID, AMBER, f"US spelling in language strings: {', '.join(shown)}{more}", url))
    if not findings:
        findings.append(Finding(ID, OK, f"{len(keys)} language strings, sorted, Australian spelling", url))
    return findings
