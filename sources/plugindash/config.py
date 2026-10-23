"""Loads config.json (written by the YunoHost scripts from the config panel)."""

from __future__ import annotations

import json
import os
from typing import Any

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
    "ci_ignore_workflows": ["release.yml"],
    "moodle_latest_branch": 0,      # 0 = look it up from moodle/moodle on GitHub.
    "directory_api": "https://download.moodle.org/api/1.3/pluginfo.php",
    # Alerts.
    "alert_on": "worse",            # "worse", "any" or "none".
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
    cfg["exclude_repos"] = [r.lower() for r in cfg["exclude_repos"]]
    cfg["severity_overrides"] = _as_overrides(cfg["severity_overrides"])
    for key in ("github_enabled", "gitlab_enabled", "include_forks"):
        cfg[key] = _as_bool(cfg[key])
    for key in ("history_days", "stale_days", "moodle_latest_branch", "smtp_port"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    if cfg["alert_on"] not in ("worse", "any", "none"):
        cfg["alert_on"] = "worse"
    cfg["gitlab_url"] = str(cfg["gitlab_url"]).rstrip("/")
    cfg["public_url"] = str(cfg["public_url"]).rstrip("/")
    return cfg


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    cfg = normalise(raw)
    cfg["_path"] = os.path.abspath(path)
    return cfg
