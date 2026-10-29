"""Helpers shared by the built-in checks."""

from __future__ import annotations

import os
from typing import Any

from ..model import Workflow
from ..phpparse import parse_version_php
from ._ci import called_workflows, fill_inputs


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


def ci_text(repo, workflow: Workflow) -> tuple[str, list[str]]:
    """The workflow's text plus the shared workflows it calls (with its inputs filled in), and the names of any
    called workflow that couldn't be read. A plugin whose moodle-ci.yml only says `uses: .../moodle-plugin-ci.yml@v1`
    then gets its matrix and steps checked where they really live."""
    text = repo.workflow_text(workflow) or ""
    parts, unreadable = [text], []
    for call in called_workflows(text):
        if call["repo"] is None:
            called = repo.file(call["path"])
            name = call["path"]
        else:
            called = repo.shared_workflow(call["repo"], call["path"], call["ref"])
            name = f"{call['repo']}/{call['path']}@{call['ref']}"
        if called is None:
            unreadable.append(name)
        else:
            parts.append(fill_inputs(called, call["inputs"]))
    return "\n".join(parts), unreadable


def plural(count: int, word: str, plural_word: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural_word or word + 's')}"
