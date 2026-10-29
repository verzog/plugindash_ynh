"""Command line: python3 run.py <command> [--config PATH]

Commands:
  run           Collect, write the dashboard files and send alerts.
  run --no-alerts
  test-alert    Send a test message through every configured channel.
  list-checks   Show the checks that will run (built-in and extensions).
  serve-run     (Used by the systemd run service) localhost endpoint for the "Run check now" button.
  write-config  (Used by the YunoHost scripts) build config.json from PD_* environment variables.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__

DEFAULT_CONFIG = "/var/www/plugindash/config.json"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def cmd_run(args) -> int:
    from .config import load
    from .runner import run
    cfg = load(args.config)
    status = run(cfg, send_alerts=not args.no_alerts)
    if not status["run"]["ok"]:
        print(f"Run failed: {status['run']['error']}", file=sys.stderr)
        return 1
    counts = status["counts"]
    print(f"OK: {len(status['repos'])} plugins: {counts['red']} red, {counts['amber']} amber, "
          f"{counts['green']} green, {counts['grey']} grey")
    for channel, result in (status.get("alerts") or {}).items():
        print(f"Alert via {channel}: {result}")
    return 0


def cmd_test_alert(args) -> int:
    from .config import load
    from .notify import send_all
    cfg = load(args.config)
    results = send_all(
        cfg, "Plugin dashboard: test alert",
        "If you can read this, alerts from your plugin dashboard are working.", "default",
        cfg.get("public_url") or None,
    )
    if not results:
        print("No alert channel is configured (ntfy, email or Matrix).")
        return 1
    for channel, result in results.items():
        print(f"{channel}: {result}")
    return 0 if all(r == "sent" for r in results.values()) else 1


def cmd_serve_run(args) -> int:
    from .config import load
    from .runserver import serve
    cfg = load(args.config)
    try:
        port = int(os.environ.get("PLUGINDASH_RUN_PORT", "0"))
    except ValueError:
        port = 0
    if port <= 0:
        print("No run port configured (set PLUGINDASH_RUN_PORT).", file=sys.stderr)
        return 1
    serve(cfg, port)
    return 0


def cmd_list_checks(args) -> int:
    from .checks import load_checks
    from .config import load
    cfg = load(args.config)
    for check in load_checks(cfg.get("extensions_dir")):
        state = "disabled" if check.ID in cfg["disabled_checks"] else "enabled"
        override = cfg["severity_overrides"].get(check.ID)
        extra = f", level override: {override}" if override else ""
        print(f"{check.ID:20} {state}{extra}  {check.TITLE}")
    return 0


# Settings that come from YunoHost as PD_<NAME> environment variables.
ENV_KEYS = (
    "public_url", "timezone", "www_dir", "data_dir", "extensions_dir",
    "github_enabled", "github_token", "github_owners", "include_forks", "exclude_repos",
    "gitlab_enabled", "gitlab_url", "gitlab_token",
    "disabled_checks", "severity_overrides", "stale_days", "ci_ignore_workflows", "moodle_latest_branch",
    "moodle_min_branch", "moodle_max_branch",
    "alert_on", "reminder_day", "ntfy_url", "ntfy_topic", "ntfy_token", "email_to", "email_from",
    "matrix_homeserver", "matrix_room", "matrix_token",
)


def cmd_write_config(args) -> int:
    from .config import normalise
    raw = {}
    for key in ENV_KEYS:
        value = os.environ.get(f"PD_{key.upper()}")
        if value is not None:
            raw[key] = value
    cfg = normalise(raw)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2)
        handle.write("\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="plugindash", description=f"Plugin Dashboard {__version__}")
    parser.add_argument("--config", default=os.environ.get("PLUGINDASH_CONFIG", DEFAULT_CONFIG))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--no-alerts", action="store_true")
    sub.add_parser("test-alert")
    sub.add_parser("list-checks")
    sub.add_parser("serve-run")
    p_write = sub.add_parser("write-config")
    p_write.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    handlers = {"run": cmd_run, "test-alert": cmd_test_alert, "list-checks": cmd_list_checks,
                "serve-run": cmd_serve_run, "write-config": cmd_write_config}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
