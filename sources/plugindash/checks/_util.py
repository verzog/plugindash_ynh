"""Helpers shared by the built-in checks."""

from __future__ import annotations

import os
from typing import Any

from ..model import Workflow
from ..phpparse import parse_version_php


def version_at(repo, ref: str | None = None) -> dict[str, Any] | None:
    """Parsed version.php at a branch or tag (never executed)."""
    text = repo.file("version.php", ref)
    return None if text is None else parse_version_php(text)


def ci_workflows(repo, cfg: dict[str, Any]) -> list[Workflow]:
    """Workflows that count as CI (release workflows and ignored ones left out)."""
    ignored = {name.lower() for name in cfg.get("ci_ignore_workflows", [])}
    result = []
    for wf in repo.workflows():
        base = os.path.basename(wf.path).lower()
        if base in ignored or wf.name.lower() in ignored:
            continue
        result.append(wf)
    return result


def plural(count: int, word: str, plural_word: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural_word or word + 's')}"
