"""Writes the files nginx serves: status.json, history.json and metrics."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from .model import STATUS_RANK


def write_atomic(path: str, text: str) -> None:
    """Write to a temp file then rename, so nginx never serves a half-written file."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(path: str, data: Any) -> None:
    write_atomic(path, json.dumps(data, indent=1, ensure_ascii=False, default=str))


def _label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prometheus(status: dict[str, Any]) -> str:
    """Prometheus text exposition format."""
    lines = [
        "# HELP plugindash_repo_status Repository colour: 0 green, 1 grey, 2 amber, 3 red.",
        "# TYPE plugindash_repo_status gauge",
    ]
    for repo in status["repos"]:
        labels = (f'repo="{_label(repo["full_name"])}",component="{_label(repo.get("component") or "")}",'
                  f'source="{_label(repo["source"])}"')
        lines.append(f"plugindash_repo_status{{{labels}}} {STATUS_RANK[repo['status']]}")
    lines += [
        "# HELP plugindash_findings Number of findings per repository and level.",
        "# TYPE plugindash_findings gauge",
    ]
    for repo in status["repos"]:
        counts: dict[str, int] = {}
        for finding in repo["findings"]:
            counts[finding["level"]] = counts.get(finding["level"], 0) + 1
        for level in ("red", "amber", "info"):
            lines.append(
                f'plugindash_findings{{repo="{_label(repo["full_name"])}",level="{level}"}} {counts.get(level, 0)}'
            )
    lines += [
        "# HELP plugindash_repos Number of repositories per colour.",
        "# TYPE plugindash_repos gauge",
    ]
    for colour, count in status["counts"].items():
        lines.append(f'plugindash_repos{{status="{colour}"}} {count}')
    run = status["run"]
    lines += [
        "# HELP plugindash_last_run_timestamp_seconds When the collector last finished (Unix time).",
        "# TYPE plugindash_last_run_timestamp_seconds gauge",
        f"plugindash_last_run_timestamp_seconds {run['finished_ts']}",
        "# HELP plugindash_last_run_success 1 if the last collector run completed.",
        "# TYPE plugindash_last_run_success gauge",
        f"plugindash_last_run_success {1 if run['ok'] else 0}",
        "# HELP plugindash_api_calls API calls made by the last run.",
        "# TYPE plugindash_api_calls gauge",
        f"plugindash_api_calls {run['api_calls']}",
    ]
    return "\n".join(lines) + "\n"
