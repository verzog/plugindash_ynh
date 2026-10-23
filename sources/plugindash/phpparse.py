"""Reads a Moodle version.php as text. The file is never executed.

Same idea as core\\update\\validator::parse_version_php(): drop comments,
then match the `$plugin->... = ...;` assignments and read their literal values.
"""

from __future__ import annotations

import re
from typing import Any

_ASSIGN = re.compile(r"\$plugin\s*->\s*(\w+)\s*=\s*(.+?)\s*;", re.S)
_LICENSE = re.compile(r"@license\s+(.+)")


def strip_comments(source: str) -> str:
    """Remove // # and /* */ comments while leaving string contents alone."""
    out = []
    i, n = 0, len(source)
    quote = None
    while i < n:
        ch = source[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif source.startswith("//", i) or (ch == "#" and not source.startswith("#[", i)):
            end = source.find("\n", i)
            i = n if end == -1 else end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_top_level(text: str) -> list[str]:
    parts, depth, current, quote = [], 0, [], None
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def parse_literal(expr: str) -> Any:
    """Turns a PHP literal into Python. Unknown expressions come back as their text."""
    expr = expr.strip()
    if not expr:
        return None
    if expr[0] in ("'", '"') and expr[-1] == expr[0] and len(expr) >= 2:
        return expr[1:-1].replace("\\" + expr[0], expr[0])
    if re.fullmatch(r"[+-]?\d+", expr):
        return int(expr)
    if re.fullmatch(r"[+-]?\d+\.\d*", expr):
        return float(expr)
    lowered = expr.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered == "null":
        return None
    inner = None
    if expr.startswith("[") and expr.endswith("]"):
        inner = expr[1:-1]
    elif re.match(r"array\s*\(", expr, re.I) and expr.endswith(")"):
        inner = expr[expr.index("(") + 1:-1]
    if inner is not None:
        items = _split_top_level(inner)
        if any("=>" in item for item in items):
            result = {}
            for item in items:
                if "=>" in item:
                    key, value = item.split("=>", 1)
                    result[parse_literal(key)] = parse_literal(value)
            return result
        return [parse_literal(item) for item in items]
    return expr  # A constant such as MATURITY_STABLE.


def parse_version_php(source: str) -> dict[str, Any]:
    """Returns the $plugin fields plus 'license' (from the @license docblock tag)."""
    result: dict[str, Any] = {}
    match = _LICENSE.search(source)
    if match:
        result["license"] = match.group(1).strip()
    for key, value in _ASSIGN.findall(strip_comments(source)):
        result[key] = parse_literal(value)
    return result


def is_moodle_plugin(fields: dict[str, Any]) -> bool:
    component = fields.get("component")
    return isinstance(component, str) and bool(re.fullmatch(r"[a-z][a-z0-9]*_[a-z0-9_]+", component))
