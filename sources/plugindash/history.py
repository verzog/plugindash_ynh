"""Daily status history in SQLite. Also tells the alerting which repos changed colour."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    repo_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS statuses (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    PRIMARY KEY (run_id, repo)
);
CREATE INDEX IF NOT EXISTS statuses_repo ON statuses(repo);
-- The colour each repo had when you were last told about it. Alerts compare against this,
-- so a change whose alert no channel delivered is sent again on the next run.
CREATE TABLE IF NOT EXISTS alert_baseline (
    repo TEXT PRIMARY KEY,
    status TEXT NOT NULL
);
-- The problems (red/amber findings) you were last told about, per repo. Alerts report what's new or gone
-- compared with this. It replaces alert_baseline, which is no longer read.
CREATE TABLE IF NOT EXISTS alert_problems (
    repo TEXT NOT NULL,
    key TEXT NOT NULL,
    problem TEXT NOT NULL,  -- JSON: check, level, message, fix, url.
    PRIMARY KEY (repo, key)
);
-- Small facts the app remembers between runs, such as whether alert_problems has been filled yet.
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class History:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def last_good_statuses(self) -> dict[str, str]:
        """Repo colours from the most recent successful run."""
        row = self.db.execute("SELECT id FROM runs WHERE ok = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return {}
        rows = self.db.execute("SELECT repo, status FROM statuses WHERE run_id = ?", (row[0],)).fetchall()
        return dict(rows)

    def alert_baseline(self) -> dict[str, str]:
        """Repo colours that alerts compare against (falls back to the last good run)."""
        rows = self.db.execute("SELECT repo, status FROM alert_baseline").fetchall()
        return dict(rows) or self.last_good_statuses()

    def set_alert_baseline(self, statuses: dict[str, str]) -> None:
        self.db.execute("DELETE FROM alert_baseline")
        self.db.executemany("INSERT INTO alert_baseline (repo, status) VALUES (?, ?)", list(statuses.items()))
        self.db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def alert_problems(self) -> dict[str, dict[str, dict[str, Any]]] | None:
        """Problems last alerted about, per repo; None until they've been stored once."""
        if self.get_meta("alert_problems_saved") is None:
            return None
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for repo, key, problem in self.db.execute("SELECT repo, key, problem FROM alert_problems"):
            result.setdefault(repo, {})[key] = json.loads(problem)
        return result

    def set_alert_problems(self, problems: dict[str, dict[str, dict[str, Any]]]) -> None:
        self.db.execute("DELETE FROM alert_problems")
        self.db.executemany(
            "INSERT INTO alert_problems (repo, key, problem) VALUES (?, ?, ?)",
            [(repo, key, json.dumps(p)) for repo, found in problems.items() for key, p in found.items()],
        )
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('alert_problems_saved', '1')")
        self.db.commit()

    def record(self, started: datetime, finished: datetime, ok: bool, error: str | None,
               statuses: dict[str, tuple[str, str]]) -> int:
        cur = self.db.execute(
            "INSERT INTO runs (started_at, finished_at, ok, error, repo_count) VALUES (?, ?, ?, ?, ?)",
            (started.isoformat(), finished.isoformat(), int(ok), error, len(statuses)),
        )
        run_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO statuses (run_id, repo, status, summary) VALUES (?, ?, ?, ?)",
            [(run_id, repo, status, summary) for repo, (status, summary) in statuses.items()],
        )
        self.db.commit()
        return run_id

    def prune(self, keep_days: int, now: datetime | None = None) -> None:
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=keep_days)).isoformat()
        self.db.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
        self.db.commit()

    def recent(self, days: int, tz) -> dict[str, list[dict[str, Any]]]:
        """Last status per repo per local day, for the dashboard's history strip."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat()
        rows = self.db.execute(
            "SELECT r.started_at, s.repo, s.status, s.summary FROM statuses s JOIN runs r ON r.id = s.run_id "
            "WHERE r.ok = 1 AND r.started_at >= ? ORDER BY r.started_at", (cutoff,),
        ).fetchall()
        per_repo: dict[str, dict[str, dict[str, Any]]] = {}
        for started, repo, status, summary in rows:
            day = datetime.fromisoformat(started).astimezone(tz).date().isoformat()
            per_repo.setdefault(repo, {})[day] = {"date": day, "status": status, "summary": summary or ""}
        return {repo: list(days_map.values())[-days:] for repo, days_map in per_repo.items()}

    def runs(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT started_at, finished_at, ok, error, repo_count FROM runs ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return [
            {"started_at": r[0], "finished_at": r[1], "ok": bool(r[2]), "error": r[3], "repo_count": r[4]}
            for r in rows
        ]
