"""One collector run: read every repo, run the checks, save outputs, send alerts."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import __version__
from .checks import Context, load_checks
from .history import History
from .http import AuthError, HttpError
from .model import AMBER, INFO, LEVEL_RANK, LEVELS, OK, RED, STATUS_RANK, Finding, worst_status
from .moodle import Directory, branch_label, supported_range
from .notify import send_all
from .output import prometheus, write_atomic, write_json
from .phpparse import is_moodle_plugin, parse_version_php
from .sources import build_sources

log = logging.getLogger("plugindash")


class FatalRunError(Exception):
    """Nothing useful could be collected (e.g. every token was rejected)."""


def _zone(cfg: dict[str, Any]):
    try:
        return ZoneInfo(cfg.get("timezone") or "UTC")
    except Exception:
        return timezone.utc


def apply_overrides(findings: list[Finding], overrides: dict[str, str]) -> list[Finding]:
    """Lets the config panel change how serious a check is, e.g. unreleased=info."""
    for finding in findings:
        level = overrides.get(finding.check)
        if level in LEVELS and finding.level in (AMBER, RED):
            finding.level = level
    return findings


def summarise(findings: list[Finding]) -> str:
    serious = sorted((f for f in findings if f.level in (RED, AMBER)), key=lambda f: -LEVEL_RANK[f.level])
    if not serious:
        return "All checks passed"
    extra = len(serious) - 1
    return serious[0].message + (f" (+{extra} more)" if extra else "")


def check_repo(repo, checks, ctx: Context) -> dict[str, Any] | None:
    """Returns the repo's dashboard entry, or None if it isn't a Moodle plugin."""
    text = repo.file("version.php")
    if text is None:
        return None
    plugin = parse_version_php(text)
    if not is_moodle_plugin(plugin):
        return None
    findings: list[Finding] = []
    if repo.archived:
        findings.append(Finding("archived", INFO, "Archived; checks skipped", repo.html_url))
    else:
        for check in checks:
            try:
                findings.extend(check.run(repo, plugin, ctx) or [])
            except AuthError as err:
                findings.append(Finding(
                    check.ID, INFO, f"{check.TITLE}: the token can't read this (HTTP {err.status})",
                ))
            except HttpError as err:
                findings.append(Finding(check.ID, INFO, f"{check.TITLE}: couldn't fetch data ({err})"))
            except Exception as err:  # A buggy check must not stop the others.
                log.exception("Check %s failed on %s", check.ID, repo.full_name)
                findings.append(Finding(check.ID, INFO, f"{check.TITLE}: check error ({err})"))
    apply_overrides(findings, ctx.cfg["severity_overrides"])
    findings.sort(key=lambda f: (-LEVEL_RANK[f.level], getattr(f, "check", "")))
    rel = None
    if not repo.archived:
        try:
            rel = repo.latest_release()
        except HttpError:
            rel = None
    supported = supported_range(plugin)
    issues = pulls = 0
    if not repo.archived:
        try:  # Already fetched (and cached) by the issues check.
            issues, pulls = len(repo.open_issues()), len(repo.open_pull_requests())
        except HttpError:
            pass
    return {
        "name": repo.name,
        "full_name": repo.full_name,
        "url": repo.html_url,
        "source": repo.source,
        "private": repo.private,
        "fork": repo.fork,
        "archived": repo.archived,
        "default_branch": repo.default_branch,
        "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
        "component": plugin.get("component"),
        "release": plugin.get("release"),
        "version": plugin.get("version"),
        "maturity": plugin.get("maturity"),
        "supported": [branch_label(supported[0]), branch_label(supported[1])] if supported else None,
        "latest_tag": rel.tag if rel else None,
        "latest_tag_url": rel.url if rel else None,
        "open_issues": issues,
        "open_prs": pulls,
        "status": worst_status(findings, archived=repo.archived),
        "summary": "Archived" if repo.archived else summarise(findings),
        "findings": [f.to_dict() for f in findings],
    }


def collect(cfg: dict[str, Any], sources=None, directory=None, now: datetime | None = None) -> dict[str, Any]:
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    sources = build_sources(cfg) if sources is None else sources
    if not sources:
        raise FatalRunError("No source is configured. Add a GitHub token in the YunoHost config panel.")

    checks = [c for c in load_checks(cfg.get("extensions_dir")) if c.ID not in cfg["disabled_checks"]]
    latest = cfg.get("moodle_latest_branch") or 0
    if not latest:
        for source in sources:
            if hasattr(source, "moodle_latest_branch"):
                latest = source.moodle_latest_branch()
                if latest:
                    break
    if directory is None and "plugins_directory" not in cfg["disabled_checks"]:
        directory = Directory(cfg["directory_api"])
    ctx = Context(cfg=cfg, now=now, moodle_latest=latest, directory=directory)

    excluded = set(cfg["exclude_repos"])
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in sources:
        try:
            repos = source.list_repos()
        except (AuthError, HttpError) as err:
            errors.append(f"{source.name}: {err.body or err}")
            continue
        todo = [
            r for r in repos
            if r.full_name.lower() not in excluded and r.name.lower() not in excluded
            and (cfg["include_forks"] or not r.fork)
        ]

        def work(repo):
            try:
                return check_repo(repo, checks, ctx)
            except AuthError as err:
                log.warning("Skipping %s: token can't read it (%s)", repo.full_name, err)
            except HttpError as err:
                log.warning("Skipping %s: %s", repo.full_name, err)
                return {
                    "name": repo.name, "full_name": repo.full_name, "url": repo.html_url, "source": repo.source,
                    "private": repo.private, "fork": repo.fork, "archived": repo.archived,
                    "default_branch": repo.default_branch, "pushed_at": None, "component": None, "release": None,
                    "version": None, "maturity": None, "supported": None, "latest_tag": None,
                    "latest_tag_url": None, "open_issues": 0, "open_prs": 0, "status": "grey",
                    "summary": f"Couldn't read the repo ({err})",
                    "findings": [Finding("collector", INFO, f"Couldn't read the repo ({err})").to_dict()],
                }
            return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            entries.extend(e for e in pool.map(work, todo) if e)

    if errors and not entries:
        raise FatalRunError("; ".join(errors))

    entries.sort(key=lambda e: (-STATUS_RANK[e["status"]], e["full_name"].lower()))
    counts = {colour: 0 for colour in ("red", "amber", "green", "grey")}
    for entry in entries:
        counts[entry["status"]] += 1
    finished = datetime.now(timezone.utc)
    return {
        "app_version": __version__,
        "generated_at": finished.isoformat(),
        "timezone": cfg.get("timezone") or "UTC",
        "moodle": {"latest_branch": latest, "latest_label": branch_label(latest) if latest else None},
        "checks": [
            {"id": c.ID, "title": c.TITLE, "description": getattr(c, "DESCRIPTION", ""),
             "override": cfg["severity_overrides"].get(c.ID)}
            for c in checks
        ],
        "counts": counts,
        "run": {
            "ok": True,
            "error": "; ".join(errors) or None,
            "started_at": now.isoformat(),
            "finished_at": finished.isoformat(),
            "finished_ts": int(finished.timestamp()),
            "duration_s": round(time.monotonic() - started, 1),
            "api_calls": sum(s.api_calls for s in sources) + (directory.client.calls if directory else 0),
        },
        "repos": entries,
    }


def changes_to_alert(previous: dict[str, str], repos: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "none" or not previous:
        return []
    changes = []
    for repo in repos:
        old = previous.get(repo["full_name"])
        new = repo["status"]
        if old is None or old == new:
            continue
        if mode == "any" or STATUS_RANK[new] > STATUS_RANK[old]:
            changes.append({"repo": repo, "old": old, "new": new})
    return changes


def alert_text(changes: list[dict[str, Any]]) -> tuple[str, str, str]:
    worse = sum(1 for c in changes if STATUS_RANK[c["new"]] > STATUS_RANK[c["old"]])
    title = f"Plugin dashboard: {len(changes)} repo{'s' if len(changes) != 1 else ''} changed"
    if worse:
        title += f" ({worse} worse)"
    lines = [f"{c['repo']['full_name']}: {c['old']} → {c['new']}. {c['repo']['summary']}" for c in changes]
    priority = "high" if any(c["new"] == "red" for c in changes) else "default"
    return title, "\n".join(lines), priority


def run(cfg: dict[str, Any], send_alerts: bool = True, sources=None, directory=None) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    www, data = cfg["www_dir"], cfg["data_dir"]
    history = History(os.path.join(data, "history.sqlite"))
    try:
        previous = history.last_good_statuses()
        try:
            status = collect(cfg, sources=sources, directory=directory, now=started)
        except FatalRunError as err:
            log.error("Run failed: %s", err)
            finished = datetime.now(timezone.utc)
            history.record(started, finished, False, str(err), {})
            status = _load(os.path.join(www, "status.json")) or {
                "repos": [], "counts": {"red": 0, "amber": 0, "green": 0, "grey": 0}, "checks": [],
                "moodle": {}, "timezone": cfg.get("timezone"), "app_version": __version__,
            }
            status["run"] = {
                "ok": False, "error": str(err), "started_at": started.isoformat(),
                "finished_at": finished.isoformat(), "finished_ts": int(finished.timestamp()),
                "duration_s": 0, "api_calls": 0,
            }
            write_json(os.path.join(www, "status.json"), status)
            write_atomic(os.path.join(www, "metrics"), prometheus(status))
            if send_alerts and cfg["alert_on"] != "none":
                send_all(cfg, "Plugin dashboard: run failed", str(err), "high", cfg.get("public_url") or None)
            return status

        finished = datetime.now(timezone.utc)
        history.record(started, finished, True, status["run"]["error"],
                       {r["full_name"]: (r["status"], r["summary"]) for r in status["repos"]})
        history.prune(cfg["history_days"])
        write_json(os.path.join(www, "status.json"), status)
        write_json(os.path.join(www, "history.json"), history.recent(30, _zone(cfg)))
        write_atomic(os.path.join(www, "metrics"), prometheus(status))

        changes = changes_to_alert(previous, status["repos"], cfg["alert_on"])
        status["alerts"] = {}
        if changes and send_alerts:
            title, body, priority = alert_text(changes)
            status["alerts"] = send_all(cfg, title, body, priority, cfg.get("public_url") or None)
        log.info(
            "Done: %d repos (%s) in %ss, %d API calls; %d alert-worthy changes",
            len(status["repos"]), ", ".join(f"{v} {k}" for k, v in status["counts"].items()),
            status["run"]["duration_s"], status["run"]["api_calls"], len(changes),
        )
        return status
    finally:
        history.close()


def _load(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
