"""Moodle-specific helpers: branch numbers and the plugins directory API."""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from .http import Client, HttpError, NotFound


def branch_label(branch: int) -> str:
    """503 -> '5.3', 405 -> '4.5', 39 -> '3.9', 311 -> '3.11'."""
    if branch <= 0:
        return "?"
    if branch >= 400:  # Moodle 4.0 onwards: 400, 405, 500, 503 ...
        return f"{branch // 100}.{branch % 100}"
    text = str(branch)
    return f"{text[0]}.{text[1:]}"


def branch_name(branch: int) -> str:
    return f"MOODLE_{branch}_STABLE"


def parse_branch(value: Any) -> int:
    """'5.1' or '501' -> 501. Returns 0 if it isn't a Moodle 4.0+ branch."""
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)\.(\d+)", text)
    if match:
        major, minor = int(match.group(1)), int(match.group(2))
        return major * 100 + minor if major >= 4 and minor < 100 else 0
    return int(text) if text.isdigit() and int(text) >= 400 else 0


# Moodle's version number at each branch's release, to check $plugin->requires against.
# Only branches whose number is known for certain are listed.
BRANCH_VERSIONS = {501: 2025100600}


def min_php(branch: int) -> tuple[int, int]:
    """Lowest PHP a Moodle branch installs on: 5.2 dropped PHP 8.2."""
    return (8, 2) if branch <= 501 else (8, 3)


def supported_range(fields: dict[str, Any]) -> tuple[int, int] | None:
    value = fields.get("supported")
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return value[0], value[1]
    return None


def release_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalise_tag(tag: str) -> str:
    return tag[1:] if tag[:1] in ("v", "V") and tag[1:2].isdigit() else tag


def version_key(text: str) -> tuple:
    """Sort key for release strings such as '1.10.2' or '2.0 (Build: 2026101500)'."""
    numbers = re.findall(r"\d+", text.split("(")[0]) or ["0"]
    return tuple(int(n) for n in numbers)


class Directory:
    """Moodle plugins directory: download.moodle.org/api/1.3/pluginfo.php (as used by Moodle core)."""

    def __init__(self, url: str, client: Client | None = None):
        self.url = url
        self.client = client or Client(timeout=20, retries=1)
        self._cache: dict[tuple[str, str], Any] = {}

    def lookup(self, component: str, branch: int) -> dict[str, Any] | None:
        """Latest directory version of `component` for a Moodle branch, or None if not listed.

        Raises HttpError if the directory can't be reached.
        """
        label = branch_label(branch)
        key = (component, label)
        if key in self._cache:
            return self._cache[key]
        params = {"plugin": component, "format": "json", "minversion": 0, "branch": label}
        try:
            raw = self.client.get_text(self.url, params)
        except NotFound:
            self._cache[key] = None
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("status") != "OK" or "pluginfo" not in data:
            raise HttpError(200, self.url, "Unexpected response from the plugins directory")
        info = data["pluginfo"]
        version = info.get("version") or {}
        result = {
            "name": info.get("name", component),
            "version": int(version.get("version") or 0),
            "release": version.get("release") or "",
            "url": f"https://moodle.org/plugins/{urllib.parse.quote(component)}",
        }
        self._cache[key] = result
        return result
