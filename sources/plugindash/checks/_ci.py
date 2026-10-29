"""Reading a moodle-plugin-ci workflow without a YAML library (the collector is standard library only).

Only what the CI checks need is picked out: the matrix cells (Moodle branch and PHP version) and the
lines that run each moodle-plugin-ci command. Anything unusual is skipped rather than guessed.

A workflow can hand its job to a shared (reusable) workflow with `uses: owner/repo/.github/workflows/x.yml@ref`.
`called_workflows()` finds those calls with their `with:` inputs, and `fill_inputs()` writes the inputs into the
shared workflow's text, so the checks read the matrix and steps that really run.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

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


def _block(lines: list[str], index: int) -> list[tuple[str, str]]:
    """The keys directly under the key on line `index`, as (key, value).

    A value is the rest of the key's line, or for a block scalar (`|`, `>-`...) the lines indented under it.
    Nested mappings come back with an empty value; read them with another _block() call.
    """
    parent = len(lines[index]) - len(lines[index].lstrip())
    result: list[tuple[str, str]] = []
    child = None
    i = index + 1
    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        if not line.strip():
            i += 1
            continue
        if indent <= parent:
            break
        match = re.match(r"^(\s*)([\w-]+)\s*:\s*(.*)$", line)
        if child is None:
            child = indent
        if match and indent == child:
            value = match.group(3)
            if re.fullmatch(r"[|>][-+]?", value.strip()):
                body = []
                i += 1
                while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                    body.append(lines[i].strip())
                    i += 1
                result.append((match.group(2), "\n".join(body).strip()))
                continue
            result.append((match.group(2), _clean(value)))
        i += 1
    return result


def _key_line(lines: list[str], key: str, indent: int | None = None, start: int = 0) -> int | None:
    """The first line from `start` that is `key:` (at `indent` spaces, if given)."""
    for i in range(start, len(lines)):
        match = re.match(rf"^(\s*){re.escape(key)}\s*:", lines[i])
        if match and (indent is None or len(match.group(1)) == indent):
            return i
    return None


_CALL = re.compile(r"^(\s*)uses\s*:\s*['\"]?([^\s'\"]+)")
_REMOTE = re.compile(r"([\w.-]+/[\w.-]+)/(\.github/workflows/[\w.-]+\.ya?ml)@([\w./-]+)")
_LOCAL = re.compile(r"\./(\.github/workflows/[\w.-]+\.ya?ml)")


def called_workflows(text: str) -> list[dict[str, Any]]:
    """Each job-level call to a shared workflow: {"repo" (None for one in this repo), "path", "ref", "inputs"}.

    Step-level `uses:` (actions such as actions/checkout) don't point at .github/workflows/, so they're skipped.
    """
    lines = strip_comments(text).splitlines()
    calls = []
    for i, line in enumerate(lines):
        match = _CALL.match(line)
        if not match:
            continue
        target = match.group(2)
        remote, local = _REMOTE.fullmatch(target), _LOCAL.fullmatch(target)
        if not remote and not local:
            continue
        if remote and ".." in remote.group(3):
            continue
        indent = len(match.group(1))
        # The job's own keys sit at the same indent as uses:; find its with: among them.
        top = i
        while top > 0 and (not lines[top - 1].strip() or len(lines[top - 1]) - len(lines[top - 1].lstrip()) >= indent):
            top -= 1
        end = i + 1
        while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) >= indent):
            end += 1
        job = lines[top:end]
        found = _key_line(job, "with", indent)
        inputs: dict[str, str] = {}
        if found is not None:
            inline = re.match(r"^\s*with\s*:\s*\{(.*)\}\s*$", job[found])  # with: {behat: false}
            inputs = _pairs(inline.group(1)) if inline else dict(_block(job, found))
        if remote:
            calls.append({"repo": remote.group(1), "path": remote.group(2), "ref": remote.group(3), "inputs": inputs})
        else:
            calls.append({"repo": None, "path": local.group(1), "ref": None, "inputs": inputs})
    return calls


def fill_inputs(called: str, inputs: dict[str, str]) -> str:
    """The shared workflow's text with each `inputs.<name>` replaced by the caller's value or the input's default.

    The `on:` section (input descriptions and defaults) is left out, so a default matrix the caller replaced
    isn't read as well.
    """
    lines = strip_comments(called).splitlines()
    values: dict[str, str] = {}
    declared = _key_line(lines, "inputs", None, _key_line(lines, "workflow_call") or 0)
    if declared is not None:
        names = [name for name, _ in _block(lines, declared)]
        for name in names:
            spot = _key_line(lines, name, None, declared)
            default = dict(_block(lines, spot)).get("default") if spot is not None else None
            if default is not None:
                values[name] = default
    values.update(inputs)
    starts = [_key_line(lines, key, 0) for key in ("on", "'on'", '"on"')]
    start = next((i for i in starts if i is not None), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", "\t"))):
            end += 1
        lines = lines[:start] + lines[end:]
    text = "\n".join(lines)

    def whole(match: re.Match) -> str:
        return values.get(match.group(1), match.group(0))

    def part(match: re.Match) -> str:
        return f"'{values[match.group(1)]}'" if match.group(1) in values else match.group(0)

    text = re.sub(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}", whole, text)  # TZ: ${{ inputs.timezone }}
    return re.sub(r"\binputs\.([\w-]+)", part, text)  # if: matrix.moodle-branch == inputs.grunt-branch


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
    # include: items in flow style, `- {moodle-branch: ..., php: ...}`, or JSON cells as a shared workflow's
    # matrix input, `{"moodle-branch": ..., "php": ...}`.
    for match in re.finditer(r"\{([^{}]*[\"']?moodle[-_]branch[\"']?\s*:[^{}]*)\}", text, re.I):
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
