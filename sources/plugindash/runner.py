"""One collector run: read every repo, run the checks, save outputs, send alerts."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import __version__, alerts
from .checks import Context, fix_for, load_checks
from .history import History
from .http import AuthError, HttpError, NotFound
from .model import AMBER, INFO, LEVEL_RANK, LEVELS, OK, RED, STATUS_RANK, Finding, worst_status
from .modes import mode_label
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
        if level in LEVELS and finding.level in (AMBER, RED) and finding.overridable:
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
                results = list(check.run(repo, plugin, ctx) or [])
                # Catch a bad level here, inside this check's error handling; later it would stop the run.
                for finding in results:
                    if not isinstance(finding, Finding) or finding.level not in LEVELS:
                        raise ValueError(f"returned an invalid finding: {finding!r}")
                    if finding.fix is None and finding.level in (RED, AMBER):
                        finding.fix = fix_for(check, finding.message)
                findings.extend(results)
            # Amber, not info, and not changed by severity overrides: a check that couldn't run
            # must not let the repo look healthy.
            except AuthError as err:
                findings.append(Finding(
                    check.ID, AMBER, f"{check.TITLE}: couldn't run, the token lacks permission (HTTP {err.status})",
                    overridable=False, fix=TOKEN_FIX.get(repo.source), incomplete=True,
                ))
            except NotFound:
                # GitHub answers 404 rather than 403 when a fine-grained token lacks a permission
                # on a private repo. Sources already turn the expected 404s (no file, no release) into None.
                findings.append(Finding(
                    check.ID, AMBER, f"{check.TITLE}: couldn't run, the server returned 404 "
                    "(usually a missing token permission)", overridable=False, fix=TOKEN_FIX.get(repo.source),
                    incomplete=True,
                ))
            except HttpError as err:
                findings.append(Finding(check.ID, INFO, f"{check.TITLE}: couldn't fetch data ({err})", incomplete=True))
            except Exception as err:  # A buggy check must not stop the others.
                log.exception("Check %s failed on %s", check.ID, repo.full_name)
                findings.append(Finding(check.ID, INFO, f"{check.TITLE}: check error ({err})", incomplete=True))
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
        "mode": mode_label(plugin),
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


# What to do when a check couldn't run because of the token.
TOKEN_FIX = {
    "github": "Give the token read access to Metadata, Contents, Issues, Pull requests, Actions and Dependabot alerts "
              "(GitHub, Settings, Developer settings, Fine-grained tokens).",
    "gitlab": "Give the token the read_api scope and access to this project.",
}

# What to grant when a token can list a repo but not read its files.
ACCESS_HINTS = {
    "github": "Give it read access to Contents.",
    "gitlab": "Give it the read_api scope and access to this project.",
}


def unreadable_entry(repo, message: str) -> dict[str, Any]:
    """Dashboard entry (grey) for a repo whose files couldn't be read."""
    return {
        "name": repo.name, "full_name": repo.full_name, "url": repo.html_url, "source": repo.source,
        "private": repo.private, "fork": repo.fork, "archived": repo.archived,
        "default_branch": repo.default_branch, "pushed_at": None, "component": None, "mode": None, "release": None,
        "version": None, "maturity": None, "supported": None, "latest_tag": None,
        "latest_tag_url": None, "open_issues": 0, "open_prs": 0, "status": "grey",
        "summary": message,
        "findings": [Finding("collector", INFO, message).to_dict()],
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
    # Repos whose files could be read, were refused, or failed otherwise (list.append is thread-safe).
    readable: list[str] = []
    denied: list[str] = []
    failed: list[str] = []
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
                entry = check_repo(repo, checks, ctx)
            except AuthError as err:
                # Shown grey rather than dropped, so a token missing read access is noticed.
                log.warning("Can't read %s: the token lacks access (%s)", repo.full_name, err)
                denied.append(repo.full_name)
                hint = ACCESS_HINTS.get(repo.source, "Give it read access to the repository.")
                return unreadable_entry(repo, f"The token can't read this repo's files (HTTP {err.status}). {hint}")
            except HttpError as err:
                log.warning("Skipping %s: %s", repo.full_name, err)
                failed.append(repo.full_name)
                return unreadable_entry(repo, f"Couldn't read the repo ({err})")
            readable.append(repo.full_name)
            return entry

        with ThreadPoolExecutor(max_workers=4) as pool:
            entries.extend(e for e in pool.map(work, todo) if e)

    if errors and not entries:
        raise FatalRunError("; ".join(errors))
    if denied and not readable and not failed:
        # Every read was refused: keep the previous results rather than a page of grey.
        errors.append(
            "The token can't read the files in any repository. Check its read access "
            "(GitHub: Contents; GitLab: the read_api scope)."
        )
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


def run(cfg: dict[str, Any], send_alerts: bool = True, sources=None, directory=None) -> dict[str, Any]:
    """Collect and write the dashboard, guarded by a lock so the daily timer and the
    on-demand 'Run check now' button never collect at the same time."""
    data = cfg["data_dir"]
    os.makedirs(data, exist_ok=True)
    lock = open(os.path.join(data, "run.lock"), "w")  # noqa: SIM115
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log.warning("Another run is already in progress; skipping this one.")
            return _skipped_status(cfg)
        return _run(cfg, send_alerts=send_alerts, sources=sources, directory=directory)
    finally:
        lock.close()


def _skipped_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """Returned when a run is skipped because another is in progress: keep the page as-is."""
    previous = _load(os.path.join(cfg["www_dir"], "status.json"))
    if previous is not None:
        return previous
    return {
        "repos": [], "counts": {"red": 0, "amber": 0, "green": 0, "grey": 0}, "checks": [],
        "moodle": {}, "timezone": cfg.get("timezone"), "app_version": __version__,
        "run": {"ok": False, "error": "another run is already in progress"},
    }


def _run(cfg: dict[str, Any], send_alerts: bool = True, sources=None, directory=None) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    www, data = cfg["www_dir"], cfg["data_dir"]
    history = History(os.path.join(data, "history.sqlite"))
    try:
        previous = history.alert_problems()
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

        # The first run (or the first after upgrading to problem-based alerts) only remembers what it found.
        found = alerts.changes(previous, status["repos"]) if previous is not None else []
        status["alerts"] = {}
        remember = True
        if send_alerts and alerts.worth_sending(found, cfg["alert_on"]):
            title, body, priority = alerts.alert_text(found, cfg.get("public_url") or None)
            status["alerts"] = send_all(cfg, title, body, priority, cfg.get("public_url") or None)
            if status["alerts"] and "sent" not in status["alerts"].values():
                # Every channel failed: remember nothing, so the next run sends this alert again.
                log.warning("No alert channel delivered; the alert will be retried on the next run")
                remember = False
        if remember:
            history.set_alert_problems(alerts.next_baseline(previous or {}, status["repos"]))
        if send_alerts:
            _weekly_reminder(cfg, history, status)
        changes = found
        log.info(
            "Done: %d repos (%s) in %ss, %d API calls; %d alert-worthy changes",
            len(status["repos"]), ", ".join(f"{v} {k}" for k, v in status["counts"].items()),
            status["run"]["duration_s"], status["run"]["api_calls"], len(changes),
        )
        return status
    finally:
        history.close()


def _weekly_reminder(cfg: dict[str, Any], history: History, status: dict[str, Any]) -> None:
    """Send the weekly list of open problems when it's due (see alerts.reminder_due)."""
    today = datetime.now(_zone(cfg)).date()
    last_text = history.get_meta("reminder_last")
    last = date.fromisoformat(last_text) if last_text else None
    if not alerts.reminder_due(today, last, cfg["reminder_day"]):
        return
    message = alerts.reminder_text(status["repos"], cfg.get("public_url") or None)
    if message is None:
        history.set_meta("reminder_last", today.isoformat())  # Nothing open: nothing to remind about.
        return
    results = send_all(cfg, *message, cfg.get("public_url") or None)
    status["reminder"] = results
    if not results or "sent" in results.values():
        history.set_meta("reminder_last", today.isoformat())
    else:
        log.warning("No channel delivered the weekly reminder; it will be tried again on the next run")


def _load(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
