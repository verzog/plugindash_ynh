"""Reading a moodle-plugin-ci workflow without a YAML library (the collector is standard library only).

Only what the CI checks need is picked out: the matrix cells (Moodle branch and PHP version) and the
lines that run each moodle-plugin-ci command. Anything unusual is skipped rather than guessed.
"""

from __future__ import annotations

import itertools
import re

_BRANCH_KEYS = ("moodle-branch", "moodle_branch")
_PHP_KEYS = ("php", "php-version", "php_version")


def strip_comments(text: str) -> str:
    """Drop # comments (a # inside quotes is kept)."""
    lines = []
    for line in text.splitlines():
        quote = None
        for i, char in enumerate(line):
            if char in ("'", '"'):
                quote = None if quote == char else (quote or char)
            elif char == "#" and quote is None and (i == 0 or line[i - 1].isspace()):
                line = line[:i]
                break
        lines.append(line.rstrip())
    return "\n".join(lines)


def _clean(value: str) -> str:
    return value.strip().strip("'\"").strip()


def _pairs(flow: str) -> dict[str, str]:
    """'moodle-branch: X, php: Y' -> {'moodle-branch': 'X', 'php': 'Y'}."""
    result = {}
    for part in flow.split(","):
        if ":" in part:
            key, value = part.split(":", 1)
            result[_clean(key).lower()] = _clean(value)
    return result


def _list(value: str) -> list[str]:
    """"['a', 'b']" -> ['a', 'b']."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return [_clean(v) for v in value[1:-1].split(",") if _clean(v)]
    return [_clean(value)] if _clean(value) else []


def _cell(raw: dict[str, str]) -> dict[str, str] | None:
    branch = next((raw[k] for k in _BRANCH_KEYS if k in raw), None)
    if branch is None:
        return None
    return {"branch": branch, "php": next((raw[k] for k in _PHP_KEYS if k in raw), "")}


def matrix_cells(text: str) -> tuple[list[dict[str, str]], bool]:
    """Matrix cells as [{'branch': 'MOODLE_501_STABLE', 'php': '8.2'}, ...], and whether they're uncertain.

    Uncertain means a cross-product matrix with an `exclude:` list, which isn't worked out here.
    """
    text = strip_comments(text)
    lines = text.splitlines()
    cells: list[dict[str, str]] = []
    # include: items in flow style, `- {moodle-branch: ..., php: ...}`.
    for match in re.finditer(r"^\s*-\s*\{([^}]*)\}", text, re.M):
        cell = _cell(_pairs(match.group(1)))
        if cell:
            cells.append(cell)
    # include: items in block style, `- moodle-branch: ...` with more keys indented below it.
    for i, line in enumerate(lines):
        start = re.match(r"^(\s*)-\s+([\w-]+)\s*:\s*(.*)$", line)
        if not start or start.group(2).lower() not in _BRANCH_KEYS + _PHP_KEYS + ("database",):
            continue
        indent = len(start.group(1))
        raw = {start.group(2).lower(): _clean(start.group(3))}
        for following in lines[i + 1:]:
            more = re.match(r"^(\s*)([\w-]+)\s*:\s*(.*)$", following)
            if not more or len(more.group(1)) <= indent:
                break
            raw[more.group(2).lower()] = _clean(more.group(3))
        cell = _cell(raw)
        if cell:
            cells.append(cell)
    if cells:
        return cells, False
    # Cross-product style, `moodle-branch: [...]` and `php: [...]`.
    found: dict[str, list[str]] = {}
    for line in lines:
        match = re.match(r"^\s*([\w-]+)\s*:\s*(\[.*\])\s*$", line)
        if match and match.group(1).lower() in _BRANCH_KEYS + _PHP_KEYS:
            found[match.group(1).lower()] = _list(match.group(2))
    branches = next((found[k] for k in _BRANCH_KEYS if k in found), [])
    phps = next((found[k] for k in _PHP_KEYS if k in found), [""])
    crossed = [{"branch": b, "php": p} for b, p in itertools.product(branches, phps)]
    return crossed, bool(crossed) and re.search(r"^\s*exclude\s*:", text, re.M) is not None


def branch_number(value: str) -> int | str | None:
    """'MOODLE_501_STABLE' -> 501, 'main'/'master' -> 'main', anything else -> None."""
    value = value.strip()
    if value.lower() in ("main", "master"):
        return "main"
    match = re.fullmatch(r"MOODLE_(\d+)_STABLE", value)
    return int(match.group(1)) if match else None


def php_version(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", value.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def command_lines(text: str, command: str) -> list[tuple[int, str]]:
    """(line number, line) for each line that runs `moodle-plugin-ci <command>`."""
    pattern = re.compile(rf"moodle-plugin-ci\s+{re.escape(command)}\b")
    return [(i, line) for i, line in enumerate(text.splitlines()) if pattern.search(line)]


def has_flag(line: str, flag: str) -> bool:
    """True if `line` passes `flag` ('--max-warnings 0' also matches '--max-warnings=0')."""
    return re.sub(r"=", " ", flag) in re.sub(r"(--[\w-]+)=", r"\1 ", line)
