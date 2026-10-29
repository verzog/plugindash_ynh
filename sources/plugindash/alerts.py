"""Working out what to tell you after a run: problems that are new, and problems that went away.

A problem is a red or amber finding. Each is remembered under a key made of its check and its message, with
standalone counts blanked out (and the plural "s" they bring), so "Last CI run was 31 days ago" turning into
"32 days ago", or "2 open issues" into "1 open issue", isn't news, but a new release tag or a different problem
is. A problem whose level rises (amber to red) counts as new. A check that didn't finish this time (a fetch
error, a missing token permission) keeps its earlier problems: they are neither fixed nor new.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Plain words for each colour, used instead of "red"/"amber" in alerts.
STATUS_WORDS = {"red": "needs fixing", "amber": "needs attention", "green": "healthy", "grey": "not checked"}
LEVEL_RANK = {"amber": 1, "red": 2}
MAX_BYTES = 3800  # ntfy turns a body over 4,096 bytes into an attachment, so longer alerts are cut short.

_COUNT = re.compile(r"(?<![\w.])\d+(?![\w.])")
_PLURAL = re.compile(r"\b(\w+?)s\b")


def problem_key(finding: dict[str, Any]) -> str:
    message = finding["message"]
    blanked = _COUNT.sub("N", message)
    if blanked != message:
        blanked = _PLURAL.sub(r"\1", blanked)  # "1 open issue" and "2 open issues" are the same problem.
    return f"{finding['check']}:{blanked}"


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


def _unfinished(repo: dict[str, Any]) -> set[str]:
    """The checks that didn't finish on this repo this time."""
    return {f["check"] for f in repo["findings"] if f.get("incomplete")}


def _carried(old: dict[str, dict[str, Any]], repo: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Earlier problems from checks that didn't finish this time: still open, as far as we know."""
    unfinished = _unfinished(repo)
    return {key: p for key, p in old.items() if p["check"] in unfinished}


def changes(previous: dict[str, dict[str, dict[str, Any]]], repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per repo with something to report: {"repo", "was", "new": [...], "fixed": [...]}."""
    result = []
    for repo in repos:
        if repo["status"] == "grey":
            continue  # Archived or unreadable: not checked this time, so nothing is new or fixed.
        old = previous.get(repo["full_name"], {})
        now = problems_of(repo)
        carried = _carried(old, repo)
        new = [p for key, p in now.items()
               if key not in old or LEVEL_RANK[p["level"]] > LEVEL_RANK.get(old[key]["level"], 0)]
        fixed = [p for key, p in old.items() if key not in now and key not in carried]
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
    """What to remember after this run.

    Grey repos, and checks that didn't finish, keep their old problems, so they aren't 'new' on return.
    """
    result = {}
    for repo in repos:
        name = repo["full_name"]
        old = previous.get(name, {})
        result[name] = old if repo["status"] == "grey" else {**_carried(old, repo), **problems_of(repo)}
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
    blocks = []
    for change in with_new:
        repo = change["repo"]
        name = repo.get("component") or repo["name"]
        now, was = repo["status"], change["was"]
        if now == was:
            state = f"still {STATUS_WORDS[now]}, {_plural(len(change['new']), 'new problem')}"
        else:
            state = f"now {STATUS_WORDS[now]} (was {STATUS_WORDS[was]})"
        block = [f"{name}: {state}"]
        for problem in sorted(change["new"], key=lambda p: -LEVEL_RANK[p["level"]]):
            block.append(f"  ✗ {problem['message']}")
            if problem.get("fix"):
                block.append(f"    What to do: {problem['fix']}")
            if problem.get("url"):
                block.append(f"    {problem['url']}")
        blocks.append("\n".join(block) + "\n")
    fixed_lines = [f"  ✓ {repo.get('component') or repo['name']}: {problem['message']}" for repo, problem in fixed]
    return title, _fit(blocks, fixed_lines, public_url), _priority(with_new)


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _fit(blocks: list[str], fixed_lines: list[str], public_url: str | None, rest: str = "with new problems") -> str:
    """The body, kept under MAX_BYTES: whole plugins first, then fixes, then a pointer to the rest."""
    where = f": {public_url}" if public_url else "."
    reserve = 200 + _size(where)  # Room for the "…and N more" lines.
    parts: list[str] = []
    used = 0
    for block in blocks:
        if used + _size(block) + reserve > MAX_BYTES:
            if not parts:  # One plugin too long on its own: show what fits of it.
                block = block.encode("utf-8")[:MAX_BYTES - reserve].decode("utf-8", "ignore") + "…\n"
                parts.append(block)
                used += _size(block) + 1
            break
        parts.append(block)
        used += _size(block) + 1
    if len(parts) < len(blocks):
        more = len(blocks) - len(parts)
        parts.append(f"…and {_plural(more, 'more plugin')} {rest}{where}\n")
        used += _size(parts[-1]) + 1
    if fixed_lines:
        lines = ["Fixed since the last check:"]
        used += _size(lines[0]) + 1
        for line in fixed_lines:
            if used + _size(line) + reserve > MAX_BYTES:
                break
            lines.append(line)
            used += _size(line) + 1
        shown = len(lines) - 1
        if shown < len(fixed_lines):
            lines.append(f"  …and {len(fixed_lines) - shown} more{where}")
        parts.append("\n".join(lines))
    return "\n".join(parts).rstrip()


def _priority(with_new: list[dict[str, Any]]) -> str:
    return "high" if any(p["level"] == "red" for c in with_new for p in c["new"]) else "default"


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def reminder_due(today: date, last: date | None, day: str, pending: bool = False) -> bool:
    """On the chosen weekday, once; or the next run after a missed one (a week since the last), or after
    one that no channel delivered (pending)."""
    if day not in WEEKDAYS:
        return False
    if last == today:
        return False
    if pending or today.weekday() == WEEKDAYS.index(day):
        return True
    return last is not None and (today - last).days >= 7


def reminder_text(repos: list[dict[str, Any]], public_url: str | None = None) -> tuple[str, str, str] | None:
    """(title, body, priority) listing everything still needing work, or None if all is well."""
    open_repos = [r for r in repos if r["status"] in ("red", "amber") and problems_of(r)]
    if not open_repos:
        return None
    open_repos.sort(key=lambda r: (r["status"] != "red", (r.get("component") or r["name"]).lower()))
    count = sum(len(problems_of(r)) for r in open_repos)
    title = (f"Plugin dashboard: weekly reminder, {_plural(count, 'open problem')} in "
             f"{_plural(len(open_repos), 'plugin')}")
    blocks = []
    for repo in open_repos:
        block = [f"{repo.get('component') or repo['name']}: {STATUS_WORDS[repo['status']]}"]
        for problem in sorted(problems_of(repo).values(), key=lambda p: -LEVEL_RANK[p["level"]]):
            block.append(f"  ✗ {problem['message']}")
            if problem.get("fix"):
                block.append(f"    What to do: {problem['fix']}")
        blocks.append("\n".join(block) + "\n")
    return title, _fit(blocks, [], public_url, "still needing work"), "default"
