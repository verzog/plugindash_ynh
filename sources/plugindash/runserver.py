"""Localhost-only HTTP endpoint that starts a collector run on demand.

The dashboard page is static, so the "Run check now" button needs something
server-side to call. This tiny service binds 127.0.0.1 only and exposes just
POST /run and GET /healthz; nginx proxies /run to it, behind the app's admin SSO.
A run is spawned as a detached process and serialised by the same lock the daily
timer uses (plugindash.runner), so the button can never start an overlapping run.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

log = logging.getLogger("plugindash.runserver")


def run_in_progress(data_dir: str) -> bool:
    """True if a collector run currently holds the run lock."""
    try:
        handle = open(os.path.join(data_dir, "run.lock"), "w")  # noqa: SIM115
    except OSError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    fcntl.flock(handle, fcntl.LOCK_UN)
    handle.close()
    return False


def _spawn_run(cfg_path: str) -> None:
    """Start a detached `run.py run`; it takes the lock and outlives this request."""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.Popen(
        [sys.executable, "-I", "-B", os.path.join(app_dir, "run.py"), "--config", cfg_path, "run"],
        cwd=app_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def make_handler(cfg: dict[str, Any], trigger: Callable[[], None]) -> type[BaseHTTPRequestHandler]:
    data_dir = cfg["data_dir"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "plugindash"
        protocol_version = "HTTP/1.1"

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path.rstrip("/") == "/run":
                if run_in_progress(data_dir):
                    self._json(200, {"started": False, "running": True})
                    return
                try:
                    trigger()
                except Exception:  # Never surface internals to the browser.
                    log.exception("Could not start a run")
                    self._json(500, {"started": False, "error": "could not start a run"})
                    return
                self._json(200, {"started": True})
            else:
                self._json(404, {"error": "not found"})

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/healthz":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, *args: Any) -> None:
            pass  # Quiet: don't fill the journal with an access line per poll.

    return Handler


def serve(cfg: dict[str, Any], port: int, host: str = "127.0.0.1",
          trigger: Callable[[], None] | None = None) -> None:
    cfg_path = cfg.get("_path") or os.environ.get("PLUGINDASH_CONFIG", "")
    if trigger is None:
        trigger = lambda: _spawn_run(cfg_path)  # noqa: E731
    server = ThreadingHTTPServer((host, port), make_handler(cfg, trigger))
    log.info("Run endpoint listening on %s:%d", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
