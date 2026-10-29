"""Shared data types: findings, levels and repository status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Finding levels, from least to most serious.
OK = "ok"        # A check passed (shown only in the detail view).
INFO = "info"    # Worth knowing, never changes the colour.
AMBER = "amber"  # Needs attention soon.
RED = "red"      # Broken or inconsistent; fix before the next release.

LEVELS = (OK, INFO, AMBER, RED)
LEVEL_RANK = {OK: 0, INFO: 1, AMBER: 2, RED: 3}

# Repository colours shown on the dashboard.
GREEN = "green"
GREY = "grey"    # Archived, or the collector could not read the repo.
STATUS_RANK = {GREEN: 0, GREY: 1, AMBER: 2, RED: 3}


@dataclass
class Finding:
    """One result from one check."""

    check: str
    level: str
    message: str
    url: str | None = None
    overridable: bool = True  # False keeps severity overrides from changing the level.
    fix: str | None = None    # What to do about it, shown on the page and in alerts.
    incomplete: bool = False  # The check didn't finish, so its earlier problems can't be called fixed.

    def to_dict(self) -> dict[str, Any]:
        result = {"check": self.check, "level": self.level, "message": self.message, "url": self.url, "fix": self.fix}
        if self.incomplete:
            result["incomplete"] = True
        return result


@dataclass
class Release:
    tag: str
    name: str
    url: str | None
    published_at: datetime | None
    assets: list[dict[str, str]] = field(default_factory=list)  # Each: {"name": ..., "url": ...}


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    path: str
    state: str  # "active", "disabled_inactivity", "disabled_manually", ...


@dataclass
class Job:
    name: str
    conclusion: str          # "success", "failure", "cancelled", "skipped", ...
    allowed_failure: bool = False


@dataclass(frozen=True)
class Run:
    id: str
    conclusion: str          # Normalised: "success", "failure", "cancelled", "other".
    created_at: datetime
    url: str | None


@dataclass
class SecurityAlert:
    severity: str            # "critical", "high", "medium", "low".
    summary: str
    url: str | None = None


class NotAvailable(Exception):
    """The source cannot provide this data (feature off, plan limit, missing permission)."""


def worst_status(findings: list[Finding], archived: bool = False, unreadable: bool = False) -> str:
    """Work out a repository's colour from its findings."""
    if any(f.level == RED for f in findings):
        return RED
    if any(f.level == AMBER for f in findings):
        return AMBER
    if archived or unreadable:
        return GREY
    return GREEN
