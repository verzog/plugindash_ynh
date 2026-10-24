"""Unit tests: run with `python3 -m unittest discover -s tests` from the sources folder."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import (  # noqa: E402
    CI_YAML, NOW, SCCA_TAG, DeniedRepo, FakeDirectory, FakeRepo, FakeSource, denied_repo, failed_run, healthy_repo,
    ok_run, release, sample_directory, sample_repos, version_php,
)
from plugindash import config as config_mod  # noqa: E402
from plugindash.checks import Context, load_checks  # noqa: E402
from plugindash.model import AMBER, INFO, OK, RED, Job, SecurityAlert, Workflow  # noqa: E402
from plugindash.moodle import branch_label, normalise_tag, version_key  # noqa: E402
from plugindash.output import prometheus  # noqa: E402
from plugindash.phpparse import is_moodle_plugin, parse_version_php, strip_comments  # noqa: E402
from plugindash.runner import changes_to_alert, collect, run  # noqa: E402

CHECKS = {c.ID: c for c in load_checks()}


def ctx(**cfg):
    base = config_mod.normalise(cfg)
    return Context(cfg=base, now=NOW, moodle_latest=503, directory=FakeDirectory())


def levels(findings):
    return sorted(f.level for f in findings)


def run_check(check_id, repo, context=None):
    plugin = parse_version_php(repo.file("version.php"))
    return CHECKS[check_id].run(repo, plugin, context or ctx())


class ConfigTests(unittest.TestCase):
    def test_owner_names_are_reduced_to_the_bare_account(self):
        cfg = config_mod.normalise({"github_owners": [
            "verzog", "@verzog", "github.com/verzog",
            "https://github.com/verzog", "https://github.com/verzog/",
        ]})
        self.assertEqual(cfg["github_owners"], ["verzog"] * 5)

    def test_owner_names_accept_a_comma_separated_string(self):
        cfg = config_mod.normalise({"github_owners": "https://github.com/verzog, otherorg"})
        self.assertEqual(cfg["github_owners"], ["verzog", "otherorg"])

    def test_empty_and_host_only_owner_values_are_dropped(self):
        cfg = config_mod.normalise({"github_owners": "verzog, , https://github.com/"})
        self.assertEqual(cfg["github_owners"], ["verzog"])


class PhpParseTests(unittest.TestCase):
    def test_parses_fields_without_executing(self):
        src = version_php("local_x", "1.2.3", 2026101500)
        fields = parse_version_php(src)
        self.assertEqual(fields["component"], "local_x")
        self.assertEqual(fields["release"], "1.2.3")
        self.assertEqual(fields["version"], 2026101500)
        self.assertEqual(fields["supported"], [501, 503])
        self.assertEqual(fields["maturity"], "MATURITY_STABLE")
        self.assertIn("GPL v3", fields["license"])
        self.assertTrue(is_moodle_plugin(fields))

    def test_commented_out_assignments_are_ignored(self):
        src = "<?php\n// $plugin->release = 'old';\n/* $plugin->version = 1; */\n$plugin->release = 'new';"
        self.assertEqual(parse_version_php(src), {"release": "new"})

    def test_comment_markers_inside_strings_survive(self):
        self.assertIn("'a // b'", strip_comments("$x = 'a // b'; // gone"))

    def test_array_syntax_and_dependencies(self):
        src = "<?php $plugin->supported = array(405, 501);\n$plugin->dependencies = ['mod_book' => 2025100600];"
        fields = parse_version_php(src)
        self.assertEqual(fields["supported"], [405, 501])
        self.assertEqual(fields["dependencies"], {"mod_book": 2025100600})

    def test_non_plugin_detected(self):
        self.assertFalse(is_moodle_plugin(parse_version_php("<?php $version = 1;")))


class MoodleHelperTests(unittest.TestCase):
    def test_branch_labels(self):
        self.assertEqual(branch_label(503), "5.3")
        self.assertEqual(branch_label(405), "4.5")
        self.assertEqual(branch_label(500), "5.0")
        self.assertEqual(branch_label(311), "3.11")
        self.assertEqual(branch_label(39), "3.9")

    def test_tags(self):
        self.assertEqual(normalise_tag("v1.3.0"), "1.3.0")
        self.assertEqual(normalise_tag("1.3.0"), "1.3.0")
        self.assertEqual(normalise_tag("version-2"), "version-2")
        self.assertLess(version_key("1.9.0"), version_key("1.10.0"))


class CheckTests(unittest.TestCase):
    def test_healthy_repo_is_all_ok(self):
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        context = ctx()
        context.directory = FakeDirectory({"local_x": {"version": 2026100100, "release": "1.3.0", "url": "u"}})
        for check_id, check in CHECKS.items():
            findings = check.run(repo, parse_version_php(repo.file("version.php")), context)
            bad = [f for f in findings if f.level in (RED, AMBER)]
            self.assertEqual(bad, [], f"{check_id}: {bad}")

    def test_ci_failure_is_red(self):
        repo = healthy_repo("v/r", "local_x", runs={"1": failed_run("r2")},
                            jobs={"r2": [Job("test (MOODLE_503_STABLE, 8.4, pgsql)", "failure")]})
        self.assertEqual(levels(run_check("ci_status", repo)), [RED])

    def test_only_main_cell_failing_is_amber(self):
        repo = healthy_repo("v/r", "local_x", runs={"1": failed_run("r2")},
                            jobs={"r2": [Job("test (main, 8.4, pgsql)", "failure"),
                                         Job("test (MOODLE_501_STABLE, 8.2, pgsql)", "success")]})
        self.assertEqual(levels(run_check("ci_status", repo)), [AMBER])

    def test_main_cell_with_continue_on_error_is_amber(self):
        repo = healthy_repo("v/r", "local_x", runs={"1": ok_run("r3")},
                            jobs={"r3": [Job("test (main, 8.4, pgsql)", "failure")]})
        self.assertEqual(levels(run_check("ci_status", repo)), [AMBER])

    def test_release_workflow_is_not_ci(self):
        repo = healthy_repo("v/r", "local_x", runs={"1": ok_run(), "2": failed_run("rel")})
        self.assertEqual(levels(run_check("ci_status", repo)), [OK])

    def test_ci_disabled_by_github_is_amber(self):
        repo = healthy_repo("v/r", "local_x",
                            workflows=[Workflow("1", "CI", ".github/workflows/ci.yml", "disabled_inactivity")])
        self.assertIn(AMBER, levels(run_check("ci_activity", repo)))

    def test_stale_ci_is_amber(self):
        repo = healthy_repo("v/r", "local_x", runs={"1": ok_run(days_ago=45)})
        findings = run_check("ci_activity", repo)
        self.assertEqual(levels(findings), [AMBER])
        self.assertIn("45 days", findings[0].message)

    def test_no_ci_is_amber(self):
        repo = healthy_repo("v/r", "local_x", workflows=[])
        self.assertEqual(levels(run_check("ci_activity", repo)), [AMBER])

    def test_tag_mismatch_is_red(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._tag_files["v1.3.0"]["version.php"] = version_php("local_x", "1.2.9")
        self.assertIn(RED, levels(run_check("release_match", repo)))

    def test_main_bumped_ahead_of_tag_is_fine(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._files["version.php"] = version_php("local_x", "1.4.0", 2026110100)
        self.assertEqual(levels(run_check("release_match", repo)), [OK])

    def test_version_going_backwards_is_red(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._files["version.php"] = version_php("local_x", "1.3.0", 2025010100)
        self.assertIn(RED, levels(run_check("release_match", repo)))

    def test_no_release_is_amber(self):
        repo = healthy_repo("v/r", "local_x", release=None)
        self.assertEqual(levels(run_check("release_match", repo)), [AMBER])
        self.assertEqual(run_check("release_zip", repo), [])
        self.assertEqual(run_check("unreleased", repo), [])

    def test_missing_zip_is_red_and_misnamed_is_amber(self):
        repo = healthy_repo("v/r", "local_x", release=release("v1.3.0", "local_x", assets=False))
        self.assertEqual(levels(run_check("release_zip", repo)), [RED])
        rel = release("v1.3.0", "local_x")
        rel.assets = [{"name": "moodle-local_x-v1.3.0.zip", "url": "u"}]
        repo = healthy_repo("v/r", "local_x", release=rel)
        self.assertEqual(levels(run_check("release_zip", repo)), [AMBER])

    def test_unreleased_commits(self):
        repo = healthy_repo("v/r", "local_x", commits_since=4)
        findings = run_check("unreleased", repo)
        self.assertEqual(levels(findings), [AMBER])
        self.assertIn("4 commits", findings[0].message)

    def test_open_issues_and_prs_are_amber(self):
        repo = healthy_repo("v/r", "local_x", issues=2, prs=1)
        findings = run_check("issues", repo)
        self.assertEqual(levels(findings), [AMBER, AMBER])
        self.assertEqual({f.message for f in findings}, {"2 open issues", "1 open pull request"})

    def test_new_moodle_release_watch(self):
        repo = healthy_repo("v/r", "local_x")
        context = ctx()
        context.moodle_latest = 504
        findings = run_check("moodle_support", repo, context)
        self.assertEqual(levels(findings), [AMBER, AMBER])  # Range and CI matrix both behind.

    def test_missing_supported_is_amber(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["version.php"] = version_php("local_x", "1.3.0", supported=None)
        self.assertIn(AMBER, levels(run_check("moodle_support", repo)))

    def test_licence_mismatch_is_red(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["LICENSE"] = "MIT License\n\nPermission is hereby granted, free of charge"
        self.assertIn(RED, levels(run_check("licence", repo)))

    def test_proprietary_mode_a_is_consistent(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["version.php"] = version_php("local_x", "1.3.0", license_tag=SCCA_TAG)
        repo._files["LICENSE"] = "Copyright (c) Skin Cancer College Australasia.\nAll rights reserved."
        repo._files["README.md"] = "# X\n\n## Licence\n\nProprietary.\n"
        self.assertEqual(levels(run_check("licence", repo)), [OK])

    def test_readme_licence_mismatch_and_missing_section(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["README.md"] = "# X\n\n## License\n\nMIT\n"
        self.assertIn(AMBER, levels(run_check("licence", repo)))
        repo = healthy_repo("v/r", "local_x")
        repo._files["README.md"] = "# X\n\nNo licence here.\n"
        self.assertIn(AMBER, levels(run_check("licence", repo)))

    def test_security_alert_levels(self):
        repo = healthy_repo("v/r", "local_x", alerts=[SecurityAlert("high", "x")])
        self.assertEqual(levels(run_check("security_alerts", repo)), [RED])
        repo = healthy_repo("v/r", "local_x", alerts=[SecurityAlert("low", "x")])
        self.assertEqual(levels(run_check("security_alerts", repo)), [AMBER])
        repo = healthy_repo("v/r", "local_x", alerts=None)
        self.assertEqual(levels(run_check("security_alerts", repo)), [INFO])

    def test_plugins_directory(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0", 2026100100)
        context = ctx()
        context.directory = FakeDirectory({"local_x": {"version": 2026010100, "release": "1.2.0", "url": "u"}})
        self.assertEqual(levels(run_check("plugins_directory", repo, context)), [AMBER])
        context.directory = FakeDirectory({})
        self.assertEqual(levels(run_check("plugins_directory", repo, context)), [INFO])
        context.directory = FakeDirectory(fail=True)
        self.assertEqual(levels(run_check("plugins_directory", repo, context)), [INFO])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.cfg = config_mod.normalise({
            "www_dir": os.path.join(base, "www"), "data_dir": os.path.join(base, "data"),
            "extensions_dir": os.path.join(base, "ext"), "github_token": "x",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_run_colours(self):
        status = collect(self.cfg, sources=[FakeSource(sample_repos())], directory=sample_directory(), now=NOW)
        by_name = {r["name"]: r["status"] for r in status["repos"]}
        self.assertNotIn("flood-watcher", by_name)
        self.assertEqual(by_name["moodle-datafield_gradeentry"], "green")
        self.assertEqual(by_name["moodle-tool_automate"], "red")
        self.assertEqual(by_name["moodle-local_lessonimportpptx"], "red")
        self.assertEqual(by_name["moodle-tiny_bootstrap"], "amber")
        self.assertEqual(by_name["moodle-local_grpcalendarimport"], "amber")
        self.assertEqual(by_name["moodle-local_freshdesk"], "amber")
        self.assertEqual(by_name["moodle-tool_canvasuplifter"], "red")
        self.assertEqual(by_name["moodle-tool_imageextractor"], "green")
        self.assertEqual(by_name["moodle-local_scca_pwa"], "grey")
        self.assertEqual(status["repos"][0]["status"], "red")  # Worst first.

    def test_severity_override_and_disabled_check(self):
        self.cfg["severity_overrides"] = {"unreleased": "info"}
        self.cfg["disabled_checks"] = ["plugins_directory"]
        repo = healthy_repo("verzog/moodle-local_x", "local_x", commits_since=3)
        status = collect(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["status"], "green")
        self.assertNotIn("plugins_directory", {c["id"] for c in status["checks"]})

    def test_extension_check_is_loaded(self):
        folder = os.path.join(self.cfg["extensions_dir"], "checks")
        os.makedirs(folder)
        with open(os.path.join(folder, "has_changes.py"), "w") as handle:
            handle.write(
                "from plugindash.model import Finding, AMBER\n"
                "ID = 'changes_file'\nTITLE = 'CHANGES.md present'\n"
                "def run(repo, plugin, ctx):\n"
                "    if repo.file('CHANGES.md') is None:\n"
                "        return [Finding(ID, AMBER, 'No CHANGES.md')]\n"
                "    return []\n"
            )
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        status = collect(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["status"], "amber")
        self.assertIn("No CHANGES.md", status["repos"][0]["summary"])

    def test_extension_with_a_bad_level_does_not_stop_the_run(self):
        folder = os.path.join(self.cfg["extensions_dir"], "checks")
        os.makedirs(folder)
        with open(os.path.join(folder, "typo.py"), "w") as handle:
            handle.write(
                "from plugindash.model import Finding\n"
                "ID = 'typo'\nTITLE = 'Misspelt level'\n"
                "def run(repo, plugin, ctx):\n"
                "    return [Finding(ID, 'amberr', 'Oops')]\n"
            )
        repos = [healthy_repo("verzog/moodle-local_x", "local_x"), healthy_repo("verzog/moodle-local_y", "local_y")]
        status = collect(self.cfg, sources=[FakeSource(repos)], directory=FakeDirectory(), now=NOW)
        self.assertEqual(len(status["repos"]), 2)
        finding = next(f for f in status["repos"][0]["findings"] if f["check"] == "typo")
        self.assertEqual(finding["level"], "info")
        self.assertIn("check error", finding["message"])

    def test_full_run_writes_outputs_and_alerts_on_change(self):
        sent = []
        folder = os.path.join(self.cfg["extensions_dir"], "notify")
        os.makedirs(folder)
        log_path = os.path.join(self.tmp.name, "sent.json")
        with open(os.path.join(folder, "capture.py"), "w") as handle:
            handle.write(
                "import json\nID = 'capture'\n"
                "def configured(cfg):\n    return True\n"
                "def send(cfg, title, body, priority, url):\n"
                f"    with open({log_path!r}, 'a') as out:\n"
                "        out.write(json.dumps([title, body, priority]) + '\\n')\n"
            )
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        run(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory())
        self.assertFalse(os.path.exists(log_path))  # First run never alerts.
        repo2 = healthy_repo("verzog/moodle-local_x", "local_x", runs={"1": failed_run("r7")},
                             jobs={"r7": [Job("test (MOODLE_503_STABLE)", "failure")]})
        run(self.cfg, sources=[FakeSource([repo2])], directory=FakeDirectory())
        with open(log_path) as handle:
            sent = [json.loads(line) for line in handle]
        self.assertEqual(len(sent), 1)
        self.assertIn("green → red", sent[0][1])
        self.assertEqual(sent[0][2], "high")
        for name in ("status.json", "history.json", "metrics"):
            self.assertTrue(os.path.exists(os.path.join(self.cfg["www_dir"], name)), name)
        with open(os.path.join(self.cfg["www_dir"], "history.json")) as handle:
            history = json.load(handle)
        self.assertIn("verzog/moodle-local_x", history)

    def test_alert_no_channel_delivered_is_retried(self):
        folder = os.path.join(self.cfg["extensions_dir"], "notify")
        os.makedirs(folder)
        log_path = os.path.join(self.tmp.name, "sent.json")
        flag = os.path.join(self.tmp.name, "channel_down")
        with open(os.path.join(folder, "flaky.py"), "w") as handle:
            handle.write(
                "import json, os\nID = 'flaky'\n"
                "def configured(cfg):\n    return True\n"
                "def send(cfg, title, body, priority, url):\n"
                f"    if os.path.exists({flag!r}):\n"
                "        raise ConnectionError('channel down')\n"
                f"    with open({log_path!r}, 'a') as out:\n"
                "        out.write(json.dumps(body) + '\\n')\n"
            )
        healthy = healthy_repo("verzog/moodle-local_x", "local_x")
        broken = healthy_repo("verzog/moodle-local_x", "local_x", runs={"1": failed_run("r7")},
                              jobs={"r7": [Job("test (MOODLE_503_STABLE)", "failure")]})
        run(self.cfg, sources=[FakeSource([healthy])], directory=FakeDirectory())
        open(flag, "w").close()
        status = run(self.cfg, sources=[FakeSource([broken])], directory=FakeDirectory())
        self.assertIn("failed", status["alerts"]["flaky"])
        self.assertFalse(os.path.exists(log_path))
        os.remove(flag)  # The channel is back: the missed alert goes out on the next run.
        run(self.cfg, sources=[FakeSource([broken])], directory=FakeDirectory())
        run(self.cfg, sources=[FakeSource([broken])], directory=FakeDirectory())  # Then it isn't repeated.
        with open(log_path) as handle:
            sent = [json.loads(line) for line in handle]
        self.assertEqual(len(sent), 1)
        self.assertIn("green → red", sent[0])

    def test_fatal_run_keeps_previous_data(self):
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        run(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), send_alerts=False)

        class Broken(FakeSource):
            def list_repos(self):
                from plugindash.http import AuthError
                raise AuthError(401, "https://api.github.com/user/repos", "GitHub rejected the token")

        status = run(self.cfg, sources=[Broken([])], directory=FakeDirectory(), send_alerts=False)
        self.assertFalse(status["run"]["ok"])
        self.assertIn("rejected", status["run"]["error"])
        self.assertEqual(len(status["repos"]), 1)  # Last good data still shown.

    def test_check_the_token_cannot_run_is_amber(self):
        def no_actions_permission():
            from plugindash.http import AuthError
            raise AuthError(403, "https://api.github.com/repos/verzog/moodle-local_x/actions/workflows", "")

        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        repo.workflows = no_actions_permission
        status = collect(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["status"], "amber")
        self.assertIn("lacks permission", status["repos"][0]["summary"])

    def test_check_the_token_cannot_run_ignores_severity_overrides(self):
        def no_issues_permission():
            from plugindash.http import AuthError
            raise AuthError(403, "https://api.github.com/repos/verzog/moodle-local_x/issues", "")

        self.cfg["severity_overrides"] = {"issues": "info"}
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        repo.open_issues = no_issues_permission
        status = collect(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["status"], "amber")

    def test_check_answered_with_404_is_amber(self):
        def private_repo_without_issues_permission():
            from plugindash.http import NotFound
            raise NotFound(404, "https://api.github.com/repos/verzog/moodle-local_x/issues", "")

        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        repo.open_issues = private_repo_without_issues_permission
        status = collect(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["status"], "amber")
        self.assertIn("404", status["repos"][0]["summary"])

    def test_repo_the_token_cannot_read_is_grey(self):
        repos = [healthy_repo("verzog/moodle-local_x", "local_x"), denied_repo("verzog/moodle-local_y")]
        status = collect(self.cfg, sources=[FakeSource(repos)], directory=FakeDirectory(), now=NOW)
        by_name = {r["full_name"]: r for r in status["repos"]}
        self.assertEqual(by_name["verzog/moodle-local_x"]["status"], "green")
        self.assertEqual(by_name["verzog/moodle-local_y"]["status"], "grey")
        self.assertIn("Contents", by_name["verzog/moodle-local_y"]["summary"])

    def test_token_that_cannot_read_any_repo_keeps_previous_data(self):
        repo = healthy_repo("verzog/moodle-local_x", "local_x")
        run(self.cfg, sources=[FakeSource([repo])], directory=FakeDirectory(), send_alerts=False)
        status = run(self.cfg, sources=[FakeSource([denied_repo("verzog/moodle-local_x")])],
                     directory=FakeDirectory(), send_alerts=False)
        self.assertFalse(status["run"]["ok"])
        self.assertIn("Contents", status["run"]["error"])
        self.assertEqual(status["repos"][0]["status"], "green")  # Last good data still shown.

    def test_refused_and_other_read_errors_are_not_blamed_on_the_token(self):
        class Broken(FakeRepo):
            def file(self, path, ref=None):
                from plugindash.http import HttpError
                raise HttpError(500, "https://gitlab.example.com/api/v4/projects/1/repository/files", "")

        repos = [denied_repo("verzog/moodle-local_x"), Broken("group/moodle-local_y", source="gitlab")]
        status = collect(self.cfg, sources=[FakeSource(repos)], directory=FakeDirectory(), now=NOW)
        self.assertEqual(sorted(r["status"] for r in status["repos"]), ["grey", "grey"])

    def test_gitlab_repo_the_token_cannot_read_gets_gitlab_advice(self):
        repo = DeniedRepo("group/moodle-local_x", source="gitlab")
        status = collect(self.cfg, sources=[FakeSource([repo, healthy_repo("verzog/moodle-local_y", "local_y")])],
                         directory=FakeDirectory(), now=NOW)
        entry = next(r for r in status["repos"] if r["full_name"] == "group/moodle-local_x")
        self.assertIn("read_api", entry["summary"])
        self.assertNotIn("Contents", entry["summary"])

    def test_alert_modes(self):
        repos = [{"full_name": "a", "status": "amber", "summary": ""}, {"full_name": "b", "status": "green",
                                                                         "summary": ""}]
        prev = {"a": "green", "b": "red"}
        self.assertEqual(len(changes_to_alert(prev, repos, "worse")), 1)
        self.assertEqual(len(changes_to_alert(prev, repos, "any")), 2)
        self.assertEqual(changes_to_alert(prev, repos, "none"), [])
        self.assertEqual(changes_to_alert({}, repos, "any"), [])

    def test_prometheus_output(self):
        status = collect(self.cfg, sources=[FakeSource(sample_repos())], directory=sample_directory(), now=NOW)
        text = prometheus(status)
        self.assertIn('plugindash_repo_status{repo="verzog/moodle-tool_automate"', text)
        self.assertIn("plugindash_last_run_success 1", text)
        for line in text.splitlines():
            if not line.startswith("#"):
                self.assertRegex(line, r'^[a-z_]+(\{.*\})? -?\d+(\.\d+)?$')


class ConfigTests(unittest.TestCase):
    def test_tags_and_overrides_from_yunohost_strings(self):
        cfg = config_mod.normalise({
            "github_owners": "verzog, educheckout", "exclude_repos": "Moodle-Old,",
            "severity_overrides": "unreleased=info,issues = AMBER", "include_forks": "0", "stale_days": "x",
            "alert_on": "bogus",
        })
        self.assertEqual(cfg["github_owners"], ["verzog", "educheckout"])
        self.assertEqual(cfg["exclude_repos"], ["moodle-old"])
        self.assertEqual(cfg["severity_overrides"], {"unreleased": "info", "issues": "amber"})
        self.assertFalse(cfg["include_forks"])
        self.assertEqual(cfg["stale_days"], 30)
        self.assertEqual(cfg["alert_on"], "worse")


if __name__ == "__main__":
    unittest.main()
