"""Loads config.json (written by the YunoHost scripts from the config panel)."""

from __future__ import annotations

import json
import os
from typing import Any

from .moodle import parse_branch

DEFAULTS: dict[str, Any] = {
    # Where the dashboard lives (used for links in alerts).
    "public_url": "",
    "timezone": "Australia/Brisbane",
    # Output and state.
    "www_dir": "/var/www/plugindash/www",
    "data_dir": "/home/yunohost.app/plugindash",
    "extensions_dir": "/home/yunohost.app/plugindash/extensions",
    "history_days": 365,
    # GitHub.
    "github_enabled": True,
    "github_api": "https://api.github.com",
    "github_token": "",
    "github_owners": ["verzog"],
    "include_forks": True,
    "exclude_repos": [],
    # GitLab (self-hosted).
    "gitlab_enabled": False,
    "gitlab_url": "",
    "gitlab_token": "",
    # Checks.
    "disabled_checks": [],
    "severity_overrides": {},        # e.g. {"unreleased": "info"}
    "stale_days": 30,
    # The supported Moodle range plugins are held to (see the moodle_baseline and ci_setup checks).
    "moodle_min_branch": "5.1",
    "moodle_max_branch": "5.3",
    # "Dependabot Updates" is GitHub's own bot workflow, never the plugin's test CI.
    "ci_ignore_workflows": ["release.yml", "Dependabot Updates"],
    "moodle_latest_branch": 0,      # 0 = look it up from moodle/moodle on GitHub.
    "directory_api": "https://download.moodle.org/api/1.3/pluginfo.php",
    # Alerts.
    "alert_on": "worse",            # "worse", "any" or "none".
    "reminder_day": "mon",          # Weekly reminder of open problems: "mon".."sun", or "off".
    "ntfy_url": "",
    "ntfy_topic": "",
    "ntfy_token": "",
    "email_to": "",
    "email_from": "",
    "smtp_host": "localhost",
    "smtp_port": 25,
    "matrix_homeserver": "",
    "matrix_room": "",
    "matrix_token": "",
}

REMINDER_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LIST_KEYS = ("github_owners", "exclude_repos", "disabled_checks", "ci_ignore_workflows")


def _as_list(value: Any) -> list[str]:
    """YunoHost 'tags' settings arrive as comma-separated strings."""
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    return [str(i).strip() for i in items if str(i).strip()]


def _owner_name(value: Any) -> str:
    """Reduce a pasted profile URL or @handle to the bare account name.

    'verzog', '@verzog', 'github.com/verzog' and 'https://github.com/verzog/' all
    become 'verzog'. A GitHub account name has no dots, so a leftover host such as
    'github.com' is dropped by the caller.
    """
    text = str(value).strip()
    for sep in ("?", "#"):
        text = text.split(sep, 1)[0]
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.strip().strip("/")
    segments = [s for s in text.split("/") if s]
    # A URL such as github.com/verzog leaves a host segment first; drop it.
    if len(segments) > 1 and "." in segments[0]:
        segments = segments[1:]
    name = segments[0] if segments else ""
    return name.lstrip("@").strip()


def _as_overrides(value: Any) -> dict[str, str]:
    """Accepts {"id": "level"} or ["id=level", ...] or "id=level,id2=level"."""
    if isinstance(value, dict):
        return {str(k).strip(): str(v).strip().lower() for k, v in value.items()}
    result = {}
    for item in _as_list(value):
        if "=" in item:
            key, level = item.split("=", 1)
            result[key.strip()] = level.strip().lower()
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if v is not None})
    for key in LIST_KEYS:
        cfg[key] = _as_list(cfg[key])
    # Forgive a pasted profile URL or @handle; a real account name has no dots.
    cfg["github_owners"] = [
        name for name in (_owner_name(o) for o in cfg["github_owners"]) if name and "." not in name
    ]
    cfg["exclude_repos"] = [r.lower() for r in cfg["exclude_repos"]]
    cfg["severity_overrides"] = _as_overrides(cfg["severity_overrides"])
    for key in ("github_enabled", "gitlab_enabled", "include_forks"):
        cfg[key] = _as_bool(cfg[key])
    for key in ("history_days", "stale_days", "moodle_latest_branch", "smtp_port"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    for key, default in (("moodle_min_branch", 501), ("moodle_max_branch", 503)):
        cfg[key] = parse_branch(cfg[key]) or default
    if cfg["alert_on"] not in ("worse", "any", "none"):
        cfg["alert_on"] = "worse"
    cfg["reminder_day"] = str(cfg["reminder_day"]).strip().lower()[:3]
    if cfg["reminder_day"] not in REMINDER_DAYS + ("off",):
        cfg["reminder_day"] = "mon"
    cfg["gitlab_url"] = str(cfg["gitlab_url"]).rstrip("/")
    cfg["public_url"] = str(cfg["public_url"]).rstrip("/")
    return cfg


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    cfg = normalise(raw)
    cfg["_path"] = os.path.abspath(path)
    return cfg
