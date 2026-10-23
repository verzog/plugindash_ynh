"""GitHub and GitLab sources against a local fake API server (real HTTP client, real JSON shapes)."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import GPL3_TEXT, version_php  # noqa: E402
from plugindash import config as config_mod  # noqa: E402
from plugindash.http import Client  # noqa: E402
from plugindash.model import NotAvailable  # noqa: E402
from plugindash.moodle import Directory  # noqa: E402
from plugindash.runner import collect  # noqa: E402
from plugindash.sources.github import GitHubSource  # noqa: E402
from plugindash.sources.gitlab import GitLabSource  # noqa: E402

ROUTES: dict[str, object] = {}
SEEN: list[tuple[str, dict]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        SEEN.append((parsed.path, dict(self.headers)))
        key = parsed.path
        if "page" in query:
            key += f"?page={query['page']}"
        route = ROUTES.get(key)
        if route is None:
            self._send(404, {"message": "Not Found"})
            return
        if callable(route):
            route = route(self, query)
        status, body, headers = route if isinstance(route, tuple) else (200, route, {})
        self._send(status, body, headers)

    def _send(self, status, body, headers=None):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def setUpModule():
    global SERVER, BASE
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    BASE = f"http://127.0.0.1:{SERVER.server_address[1]}"
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()


def tearDownModule():
    SERVER.shutdown()
    SERVER.server_close()


def gh_routes():
    repo = "/repos/verzog/moodle-local_x"
    vp = version_php("local_x", "1.3.0", 2026100100)
    ROUTES.clear()
    ROUTES.update({
        "/user/repos": (200, [
            {"full_name": "verzog/moodle-local_x", "name": "moodle-local_x",
             "html_url": "https://github.com/verzog/moodle-local_x", "default_branch": "main",
             "archived": False, "fork": False, "private": True, "pushed_at": "2026-10-20T01:02:03Z",
             "owner": {"login": "verzog"}},
        ], {"Link": f'<{BASE}/user/repos?page=2>; rel="next"'}),
        "/user/repos?page=2": [
            {"full_name": "someoneelse/thing", "name": "thing", "html_url": "https://github.com/someoneelse/thing",
             "owner": {"login": "someoneelse"}},
            {"full_name": "verzog/notes", "name": "notes", "html_url": "https://github.com/verzog/notes",
             "owner": {"login": "verzog"}},
        ],
        f"{repo}/contents/version.php": lambda h, q: (200, vp, {}),
        f"{repo}/contents/LICENSE": GPL3_TEXT,
        f"{repo}/contents/README.md": "# X\n\n## License\n\nGPL v3 or later\n",
        f"{repo}/contents/.github/workflows/ci.yml": "matrix: MOODLE_503_STABLE",
        f"{repo}/releases/latest": {
            "tag_name": "v1.3.0", "name": "v1.3.0", "html_url": "https://github.com/x/releases/tag/v1.3.0",
            "published_at": "2026-10-01T00:00:00Z",
            "assets": [{"name": "local_x-v1.3.0.zip", "browser_download_url": "https://x/local_x-v1.3.0.zip"}],
        },
        f"{repo}/compare/v1.3.0...main": {"ahead_by": 2},
        f"{repo}/issues": [{"number": 1}, {"number": 2, "pull_request": {"url": "u"}}],
        f"{repo}/actions/workflows": {"workflows": [
            {"id": 11, "name": "Moodle Plugin CI", "path": ".github/workflows/ci.yml", "state": "active"},
            {"id": 12, "name": "Release zip", "path": ".github/workflows/release.yml", "state": "active"},
        ]},
        f"{repo}/actions/workflows/11/runs": {"workflow_runs": [
            {"id": 900, "status": "in_progress", "conclusion": None, "created_at": "2026-10-22T00:00:00Z"},
            {"id": 899, "status": "completed", "conclusion": "success", "created_at": "2026-10-21T00:00:00Z",
             "html_url": "https://github.com/x/actions/runs/899"},
        ]},
        f"{repo}/actions/runs/899/jobs": {"jobs": [
            {"name": "test (MOODLE_503_STABLE, 8.4, pgsql)", "conclusion": "success"},
            {"name": "test (main, 8.4, pgsql)", "conclusion": "failure"},
        ]},
        f"{repo}/dependabot/alerts": (403, {"message": "Resource not accessible by personal access token"}, {}),
        "/repos/moodle/moodle/git/matching-refs/heads/MOODLE_": [
            {"ref": "refs/heads/MOODLE_405_STABLE"}, {"ref": "refs/heads/MOODLE_503_STABLE"},
            {"ref": "refs/heads/MOODLE_39_STABLE"}, {"ref": "refs/heads/MOODLE_503_STABLE_WIP"},
        ],
        "/api/1.3/pluginfo.php": {"status": "OK", "apiver": "1.3", "pluginfo": {
            "id": 1, "name": "X", "component": "local_x",
            "version": {"id": 5, "version": 2026010100, "release": "1.2.0", "downloadurl": "https://d",
                        "downloadmd5": "m"}}},
    })


class GitHubSourceTests(unittest.TestCase):
    def setUp(self):
        gh_routes()
        SEEN.clear()
        self.cfg = config_mod.normalise({"github_token": "tok123", "github_api": BASE, "github_owners": "verzog",
                                         "extensions_dir": "/nonexistent"})
        self.source = GitHubSource(self.cfg)

    def test_listing_paginates_and_filters_owner(self):
        repos = self.source.list_repos()
        self.assertEqual([r.full_name for r in repos], ["verzog/moodle-local_x", "verzog/notes"])
        self.assertEqual(SEEN[0][1].get("Authorization"), "Bearer tok123")

    def test_repo_methods(self):
        repo = self.source.list_repos()[0]
        self.assertIn("local_x", repo.file("version.php"))
        self.assertIsNone(repo.file("missing.txt"))
        rel = repo.latest_release()
        self.assertEqual((rel.tag, rel.assets[0]["name"]), ("v1.3.0", "local_x-v1.3.0.zip"))
        self.assertEqual(repo.commits_since("v1.3.0"), 2)
        self.assertEqual((len(repo.open_issues()), len(repo.open_pull_requests())), (1, 1))
        wf = repo.workflows()[0]
        run = repo.latest_run(wf)
        self.assertEqual((run.id, run.conclusion), ("899", "success"))  # Skips the in-progress run.
        self.assertEqual(len(repo.run_jobs(run)), 2)
        with self.assertRaises(NotAvailable):
            repo.security_alerts()
        self.assertEqual(self.source.moodle_latest_branch(), 503)

    def test_end_to_end_collect(self):
        directory = Directory(f"{BASE}/api/1.3/pluginfo.php", Client())
        status = collect(self.cfg, sources=[self.source], directory=directory)
        self.assertEqual(len(status["repos"]), 1)  # "notes" has no version.php.
        repo = status["repos"][0]
        self.assertEqual(repo["status"], "amber")
        messages = {f["check"]: f["message"] for f in repo["findings"] if f["level"] == "amber"}
        self.assertIn("unreleased", messages)
        self.assertIn("issues", messages)
        self.assertIn("plugins_directory", messages)
        self.assertIn("allowed-to-fail", messages["ci_status"])
        self.assertEqual(status["moodle"]["latest_label"], "5.3")
        self.assertGreater(status["run"]["api_calls"], 10)

    def test_bad_token_is_fatal_with_clear_message(self):
        ROUTES["/user/repos"] = (401, {"message": "Bad credentials"}, {})
        from plugindash.runner import FatalRunError
        with self.assertRaises(FatalRunError) as ctx:
            collect(self.cfg, sources=[self.source], directory=None)
        self.assertIn("GitHub rejected the token", str(ctx.exception))


class GitLabSourceTests(unittest.TestCase):
    def setUp(self):
        ROUTES.clear()
        SEEN.clear()
        p = "/api/v4/projects/7"
        vp = version_php("block_y", "2.0.0", 2026090100)
        ROUTES.update({
            "/api/v4/projects": [{"id": 7, "path_with_namespace": "verzog/moodle-block_y", "path": "moodle-block_y",
                                  "web_url": "https://gitlab.example/verzog/moodle-block_y",
                                  "default_branch": "main", "archived": False, "visibility": "private",
                                  "last_activity_at": "2026-10-20T00:00:00Z"}],
            f"{p}/repository/files/version.php/raw": vp,
            f"{p}/repository/files/.gitlab-ci.yml/raw": "MOODLE_503_STABLE",
            f"{p}/releases": [{"tag_name": "v2.0.0", "name": "v2.0.0", "released_at": "2026-10-01T00:00:00Z",
                               "assets": {"links": [{"name": "block_y-v2.0.0.zip", "url": "https://z"}]},
                               "_links": {"self": "https://gitlab.example/r"}}],
            f"{p}/repository/compare": {"commits": []},
            f"{p}/issues": [],
            f"{p}/merge_requests": [{"iid": 1}],
            f"{p}/pipelines": [{"id": 55, "status": "running"},
                               {"id": 54, "status": "failed", "created_at": "2026-10-21T00:00:00Z",
                                "web_url": "https://gitlab.example/p/54"}],
            f"{p}/pipelines/54/jobs": [{"name": "phpunit 503", "status": "failed", "allow_failure": False}],
        })
        self.cfg = config_mod.normalise({"gitlab_enabled": True, "gitlab_url": BASE, "gitlab_token": "glt",
                                         "github_enabled": False, "moodle_latest_branch": 503,
                                         "extensions_dir": "/nonexistent", "disabled_checks": "plugins_directory"})

    def test_collect_from_gitlab(self):
        source = GitLabSource(self.cfg)
        status = collect(self.cfg, sources=[source], directory=None)
        repo = status["repos"][0]
        self.assertEqual(repo["source"], "gitlab")
        self.assertEqual(repo["status"], "red")  # Pipeline failed on a real job.
        levels = {f["check"]: f["level"] for f in repo["findings"]}
        self.assertEqual(levels["ci_status"], "red")
        self.assertEqual(levels["issues"], "amber")      # One open merge request.
        self.assertEqual(levels["release_zip"], "ok")
        self.assertEqual(levels["security_alerts"], "info")
        self.assertTrue(any(h.get("Private-Token") == "glt" or h.get("PRIVATE-TOKEN") == "glt" for _, h in SEEN))


if __name__ == "__main__":
    unittest.main()
