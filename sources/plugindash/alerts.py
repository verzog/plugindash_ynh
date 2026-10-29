"""Working out what to tell you after a run: problems that are new, and problems that went away.

A problem is a red or amber finding. Each is remembered under a key made of its check and its message, with
standalone counts blanked out, so "Last CI run was 31 days ago" turning into "32 days ago" isn't news, but
a new release tag or a different problem is. A problem whose level rises (amber to red) counts as new.
"""

from __future__ import annotations

import re
from typing import Any

# Plain words for each colour, used instead of "red"/"amber" in alerts.
STATUS_WORDS = {"red": "needs fixing", "amber": "needs attention", "green": "healthy", "grey": "not checked"}
LEVEL_RANK = {"amber": 1, "red": 2}
MAX_PLUGINS = 10  # Longer alerts are cut short with a pointer to the dashboard (ntfy allows 4 KB).

_COUNT = re.compile(r"(?<![\w.])\d+(?![\w.])")


def problem_key(finding: dict[str, Any]) -> str:
    return f"{finding['check']}:{_COUNT.sub('N', finding['message'])}"


def problems_of(repo: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The repo's red and amber findings, by problem key."""
    return {
        problem_key(f): {"check": f["check"], "level": f["level"], "message": f["message"],
                         "fix": f.get("fix"), "url": f.get("url")}
        for f in repo["findings"] if f["level"] in LEVEL_RANK
    }


def _was(old: dict[str, dict[str, Any]]) -> str:
    """The repo's colour last time, from the problems remembered for it."""
    levels = {p["level"] for p in old.values()}
    return "red" if "red" in levels else ("amber" if "amber" in levels else "green")


def changes(previous: dict[str, dict[str, dict[str, Any]]], repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per repo with something to report: {"repo", "was", "new": [...], "fixed": [...]}."""
    result = []
    for repo in repos:
        if repo["status"] == "grey":
            continue  # Archived or unreadable: not checked this time, so nothing is new or fixed.
        old = previous.get(repo["full_name"], {})
        now = problems_of(repo)
        new = [p for key, p in now.items()
               if key not in old or LEVEL_RANK[p["level"]] > LEVEL_RANK.get(old[key]["level"], 0)]
        fixed = [p for key, p in old.items() if key not in now]
        if new or fixed:
            result.append({"repo": repo, "was": _was(old), "new": new, "fixed": fixed})
    return result


def worth_sending(found: list[dict[str, Any]], mode: str) -> bool:
    """'worse' sends when a problem appears; 'any' also when one goes away; 'none' never."""
    if mode == "none":
        return False
    if mode == "any":
        return bool(found)
    return any(change["new"] for change in found)


def next_baseline(previous: dict[str, dict[str, dict[str, Any]]],
                  repos: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """What to remember after this run. Grey repos keep their old problems, so they aren't 'new' on return."""
    result = {}
    for repo in repos:
        name = repo["full_name"]
        result[name] = previous.get(name, {}) if repo["status"] == "grey" else problems_of(repo)
    return result


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def alert_text(found: list[dict[str, Any]], public_url: str | None = None) -> tuple[str, str, str]:
    """(title, body, priority) for an alert about these changes."""
    with_new = [c for c in found if c["new"]]
    fixed = [(c["repo"], p) for c in found for p in c["fixed"]]
    new_count = sum(len(c["new"]) for c in with_new)
    if new_count:
        title = (f"Plugin dashboard: {_plural(new_count, 'new problem')} in "
                 f"{_plural(len(with_new), 'plugin')}")
        if fixed:
            title += f", {len(fixed)} fixed"
    else:
        title = f"Plugin dashboard: {_plural(len(fixed), 'problem')} fixed"
    lines: list[str] = []
    for change in with_new[:MAX_PLUGINS]:
        repo = change["repo"]
        name = repo.get("component") or repo["name"]
        now, was = repo["status"], change["was"]
        if now == was:
            state = f"still {STATUS_WORDS[now]}, {_plural(len(change['new']), 'new problem')}"
        else:
            state = f"now {STATUS_WORDS[now]} (was {STATUS_WORDS[was]})"
        lines.append(f"{name}: {state}")
        for problem in sorted(change["new"], key=lambda p: -LEVEL_RANK[p["level"]]):
            lines.append(f"  ✗ {problem['message']}")
            if problem.get("fix"):
                lines.append(f"    What to do: {problem['fix']}")
            if problem.get("url"):
                lines.append(f"    {problem['url']}")
        lines.append("")
    if len(with_new) > MAX_PLUGINS:
        more = len(with_new) - MAX_PLUGINS
        where = f": {public_url}" if public_url else "."
        lines.append(f"…and {_plural(more, 'more plugin')} with new problems{where}")
        lines.append("")
    if fixed:
        lines.append("Fixed since the last check:")
        for repo, problem in fixed[:MAX_PLUGINS * 2]:
            lines.append(f"  ✓ {repo.get('component') or repo['name']}: {problem['message']}")
    priority = "high" if any(p["level"] == "red" for c in with_new for p in c["new"]) else "default"
    return title, "\n".join(lines).rstrip(), priority
