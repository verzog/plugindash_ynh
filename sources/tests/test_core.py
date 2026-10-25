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
    CI_YAML, NOW, SCCA_PHPCS, SCCA_TAG, DeniedRepo, FakeDirectory, FakeRepo, FakeSource, denied_repo, failed_run,
    healthy_repo, lang_file_text, ok_run, release, sample_directory, sample_repos, version_php,
)
from plugindash import config as config_mod  # noqa: E402
from plugindash.checks import Context, load_checks  # noqa: E402
from plugindash.model import AMBER, INFO, OK, RED, Job, SecurityAlert, Workflow  # noqa: E402
from plugindash.checks._ci import matrix_cells  # noqa: E402
from plugindash.checks.lang_strings import lang_file  # noqa: E402
from plugindash.modes import MODE_A, MODE_B, mode_label, plugin_mode  # noqa: E402
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

    def test_tag_mismatch_message_shows_the_normalised_tag(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._tag_files["v1.3.0"]["version.php"] = version_php("local_x", "v1.3.0")
        findings = run_check("release_match", repo)
        self.assertIn(RED, levels(findings))
        message = next(f.message for f in findings if f.level == RED)
        self.assertIn("'1.3.0'", message)   # What the tag expects.
        self.assertIn("'v1.3.0'", message)  # What is actually in version.php.

    def test_main_bumped_ahead_of_tag_is_fine(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._files["version.php"] = version_php("local_x", "1.4.0", 2026110100)
        self.assertEqual(levels(run_check("release_match", repo)), [OK])

    def test_version_going_backwards_is_red(self):
        repo = healthy_repo("v/r", "local_x", "1.3.0")
        repo._files["version.php"] = version_php("local_x", "1.3.0", 2025010100)
        self.assertIn(RED, levels(run_check("release_match", repo)))

    def test_no_release_is_info(self):
        # An unreleased plugin isn't unhealthy, so it stays green (info, not amber).
        repo = healthy_repo("v/r", "local_x", release=None)
        self.assertEqual(levels(run_check("release_match", repo)), [INFO])
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


def scca_repo(private=True, **overrides):
    """An in-house (Mode A) plugin: SCCA @license on the default branch and at its tag."""
    repo = healthy_repo("v/r", "local_x", private=private, **overrides)
    repo._files["version.php"] = version_php("local_x", "1.3.0", license_tag=SCCA_TAG)
    repo._tag_files["v1.3.0"]["version.php"] = repo._files["version.php"]
    repo._files["LICENSE"] = "Copyright (c) Skin Cancer College Australasia.\nAll rights reserved.\n"
    repo._files["README.md"] = "# X\n\n## Licence\n\nProprietary. All rights reserved.\n"
    repo._files[".phpcs.xml"] = SCCA_PHPCS
    return repo


class LicenceModeTests(unittest.TestCase):
    def test_modes_from_the_licence_tag(self):
        self.assertEqual(plugin_mode(parse_version_php(version_php("local_x", "1.0"))), MODE_B)
        self.assertEqual(plugin_mode(parse_version_php(version_php("local_x", "1.0", license_tag=SCCA_TAG))), MODE_A)
        self.assertEqual(mode_label({"license": SCCA_TAG}), "SCCA")
        self.assertEqual(mode_label({"license": "GNU GPL v3 or later"}), "GPL")
        self.assertEqual(mode_label({"license": "MIT"}), "Other licence")
        self.assertEqual(mode_label({}), "No licence")

    def test_public_in_house_repo_is_red(self):
        self.assertEqual(levels(run_check("licence_mode", scca_repo(private=False))), [RED])
        self.assertEqual(levels(run_check("licence_mode", scca_repo())), [OK])
        self.assertEqual(levels(run_check("licence_mode", healthy_repo("v/r", "local_x"))), [OK])

    def test_in_house_release_rules_are_softer(self):
        no_zip = scca_repo(release=release("v1.3.0", "local_x", assets=False))
        self.assertEqual(levels(run_check("release_zip", no_zip)), [INFO])
        self.assertEqual(levels(run_check("unreleased", scca_repo(commits_since=3))), [INFO])
        # Mode B keeps the full rules.
        gpl_no_zip = healthy_repo("v/r", "local_x", release=release("v1.3.0", "local_x", assets=False))
        self.assertEqual(levels(run_check("release_zip", gpl_no_zip)), [RED])

    def test_in_house_plugin_must_not_be_in_the_directory(self):
        context = ctx()
        context.directory = FakeDirectory({"local_x": {"version": 2026100100, "release": "1.3.0", "url": "u"}})
        self.assertEqual(levels(run_check("plugins_directory", scca_repo(), context)), [RED])
        context.directory = FakeDirectory({})
        self.assertEqual(levels(run_check("plugins_directory", scca_repo(), context)), [OK])

    def test_mode_is_on_the_dashboard_entry(self):
        status = collect(config_mod.normalise({"github_token": "x"}), sources=[FakeSource([scca_repo()])],
                         directory=FakeDirectory(), now=NOW)
        self.assertEqual(status["repos"][0]["mode"], "SCCA")
        self.assertEqual(status["repos"][0]["status"], "green")


def ci_repo(text, **overrides):
    repo = healthy_repo("v/r", "local_x", **overrides)
    repo._files[".github/workflows/moodle-ci.yml"] = text
    return repo


class CiSetupTests(unittest.TestCase):
    def test_matrix_styles(self):
        flow, uncertain = matrix_cells(CI_YAML)
        self.assertFalse(uncertain)
        self.assertIn({"branch": "MOODLE_501_STABLE", "php": "8.2"}, flow)
        block = "matrix:\n  include:\n    - moodle-branch: MOODLE_502_STABLE\n      php: '8.2'\n"
        self.assertEqual(matrix_cells(block)[0], [{"branch": "MOODLE_502_STABLE", "php": "8.2"}])
        crossed = "matrix:\n  php: ['8.2', '8.3']\n  moodle-branch: ['MOODLE_501_STABLE']\n"
        self.assertEqual(len(matrix_cells(crossed)[0]), 2)
        self.assertTrue(matrix_cells(crossed + "  exclude:\n    - php: '8.2'\n")[1])

    def test_conventional_workflow_is_ok(self):
        self.assertEqual(levels(run_check("ci_setup", ci_repo(CI_YAML))), [OK])

    def test_php_a_branch_cannot_install_on_is_red(self):
        text = CI_YAML.replace("'MOODLE_502_STABLE', php: '8.3'", "'MOODLE_502_STABLE', php: '8.2'")
        findings = run_check("ci_setup", ci_repo(text))
        self.assertEqual(levels(findings), [RED])
        self.assertIn("Moodle 5.2 on PHP 8.2", findings[0].message)

    def test_matrix_conventions(self):
        old = CI_YAML.replace("'MOODLE_502_STABLE'", "'MOODLE_500_STABLE'")
        self.assertIn("below the 5.1 baseline", run_check("ci_setup", ci_repo(old))[0].message)
        no_main = CI_YAML.replace("- {moodle-branch: 'main'", "# - {moodle-branch: 'main'")
        self.assertIn("No Moodle main cell", run_check("ci_setup", ci_repo(no_main))[0].message)
        strict_main = CI_YAML.replace("continue-on-error: ${{ matrix.moodle-branch == 'main' }}", "")
        self.assertIn("allowed to fail", run_check("ci_setup", ci_repo(strict_main))[0].message)

    def test_tz_flags_grunt_travis_and_release(self):
        no_tz = CI_YAML.replace("TZ: Australia/Sydney", "")
        self.assertIn("doesn't set TZ", run_check("ci_setup", ci_repo(no_tz))[0].message)
        brisbane = CI_YAML.replace("Australia/Sydney", "Australia/Brisbane")
        self.assertIn("use Australia/Sydney", run_check("ci_setup", ci_repo(brisbane))[0].message)
        lax = CI_YAML.replace("phpcs --max-warnings 0", "phpcs").replace("--fail-on-warning", "")
        message = run_check("ci_setup", ci_repo(lax))[0].message
        self.assertIn("phpcs --max-warnings 0", message)
        self.assertIn("phpunit --fail-on-warning", message)
        self.assertNotIn("phpdoc", message)
        everywhere = CI_YAML.replace("matrix.moodle-branch == 'MOODLE_501_STABLE'", "true")
        self.assertIn("Grunt runs on every branch", run_check("ci_setup", ci_repo(everywhere))[0].message)
        travis = ci_repo(CI_YAML)
        travis._files[".travis.yml"] = "language: php\n"
        self.assertIn(".travis.yml", run_check("ci_setup", travis)[0].message)
        ci_only = [Workflow("1", "Moodle Plugin CI", ".github/workflows/moodle-ci.yml", "active")]
        self.assertIn("No release workflow", run_check("ci_setup", ci_repo(CI_YAML, workflows=ci_only))[0].message)
        in_house = scca_repo(workflows=ci_only)
        self.assertEqual(levels(run_check("ci_setup", in_house)), [OK])

    def test_gitlab_only_gets_the_common_rules(self):
        repo = ci_repo(CI_YAML.replace("- {moodle-branch: 'main'", "# none"), source="gitlab")
        self.assertEqual(levels(run_check("ci_setup", repo)), [OK])

    def test_baseline_follows_the_configured_range(self):
        context = ctx(moodle_min_branch="5.2")
        self.assertIn("below the 5.2 baseline", run_check("ci_setup", ci_repo(CI_YAML), context)[0].message)
        self.assertEqual(config_mod.normalise({"moodle_min_branch": "501"})["moodle_min_branch"], 501)
        self.assertEqual(config_mod.normalise({"moodle_max_branch": "nonsense"})["moodle_max_branch"], 503)


class MoodleBaselineTests(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(levels(run_check("moodle_baseline", healthy_repo("v/r", "local_x"))), [OK])
        repo = healthy_repo("v/r", "local_x")
        repo._files["version.php"] = version_php("local_x", "v1.3.0", supported="[500, 503]", requires=2025041400)
        messages = " | ".join(f.message for f in run_check("moodle_baseline", repo))
        self.assertIn("older than Moodle 5.1", messages)
        self.assertIn("starts at 5.0", messages)
        self.assertIn("the tag carries the 'v'", messages)


class RepoFilesTests(unittest.TestCase):
    def test_conventional_repos_are_ok(self):
        self.assertEqual(levels(run_check("repo_files", healthy_repo("v/r", "local_x"))), [OK])
        self.assertEqual(levels(run_check("repo_files", scca_repo())), [OK])

    def test_boilerplate_sniff_follows_the_licence_mode(self):
        no_exclusion = scca_repo()
        del no_exclusion._files[".phpcs.xml"]
        self.assertEqual(levels(run_check("repo_files", no_exclusion)), [RED])
        inline = scca_repo()
        del inline._files[".phpcs.xml"]
        inline._files["version.php"] = inline._files["version.php"].replace(
            "<?php\n", "<?php\n// phpcs:disable moodle.Files.BoilerplateComment\n", 1)
        self.assertEqual(levels(run_check("repo_files", inline)), [OK])
        dist = scca_repo()
        dist._files["phpcs.xml.dist"] = dist._files.pop(".phpcs.xml")
        self.assertEqual(levels(run_check("repo_files", dist)), [OK])
        gpl = healthy_repo("v/r", "local_x")
        gpl._files[".phpcs.xml"] = SCCA_PHPCS
        self.assertIn("keep the moodle.Files.BoilerplateComment", run_check("repo_files", gpl)[0].message)

    def test_copyright_holder_follows_the_licence_mode(self):
        gpl = healthy_repo("v/r", "local_x")
        gpl._files["version.php"] = version_php("local_x", "1.3.0", copyright="© Skin Cancer College Australasia")
        self.assertIn("a GPL plugin uses", run_check("repo_files", gpl)[0].message)
        educheckout = healthy_repo("v/r", "local_x")
        educheckout._files["version.php"] = version_php("local_x", "1.3.0",
                                                        copyright="2026 Vernon Spain trading as EduCheckout")
        self.assertEqual(levels(run_check("repo_files", educheckout)), [OK])
        scca = scca_repo()
        scca._files["version.php"] = version_php("local_x", "1.3.0", license_tag=SCCA_TAG,
                                                 copyright="2026 Vernon Spain")
        self.assertIn("an SCCA plugin uses", run_check("repo_files", scca)[0].message)
        fork = healthy_repo("v/r", "local_x", fork=True)
        fork._files["version.php"] = version_php("local_x", "1.3.0", copyright="2015 Someone Else")
        self.assertEqual(levels(run_check("repo_files", fork)), [OK])

    def test_gitattributes_and_privacy_provider(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files[".gitattributes"] = "/.github export-ignore\n"
        message = run_check("repo_files", repo)[0].message
        self.assertIn("eol=lf", message)
        self.assertIn("/tests export-ignore", message)
        in_house = scca_repo()
        in_house._files[".gitattributes"] = "* text=auto eol=lf\n"
        self.assertEqual(levels(run_check("repo_files", in_house)), [OK])  # No release zip, so no export-ignore.
        bare = healthy_repo("v/r", "local_x")
        del bare._files[".gitattributes"], bare._files["classes/privacy/provider.php"]
        messages = " | ".join(f.message for f in run_check("repo_files", bare))
        self.assertIn("No .gitattributes", messages)
        self.assertIn("No Privacy API provider", messages)


class LangStringsTests(unittest.TestCase):
    def test_sorted_australian_strings_are_ok(self):
        self.assertEqual(levels(run_check("lang_strings", healthy_repo("v/r", "local_x"))), [OK])

    def test_missing_unsorted_and_repeated(self):
        repo = healthy_repo("v/r", "local_x")
        del repo._files["lang/en/local_x.php"]
        self.assertIn("No language file (lang/en/local_x.php)", run_check("lang_strings", repo)[0].message)
        repo._files["lang/en/local_x.php"] = lang_file_text("local_x", {"zeta": "Z", "alpha": "A"})
        self.assertIn("'alpha' comes after 'zeta'", run_check("lang_strings", repo)[0].message)
        # C order puts capitals and ':' before lower case, unlike a dictionary sort.
        repo._files["lang/en/local_x.php"] = lang_file_text("local_x", {"Zed": "Z", "a:b": "x", "ab": "y"})
        self.assertEqual(levels(run_check("lang_strings", repo)), [OK])
        repo._files["lang/en/local_x.php"] = "<?php\n$string['a'] = 'x';\n$string['a'] = 'y';\n"
        self.assertIn("Repeated language string keys: a", run_check("lang_strings", repo)[0].message)

    def test_us_spellings(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["lang/en/local_x.php"] = lang_file_text("local_x", {
            "a": "Customize the color of {$a->color}", "b": "Course enrollment behavior", "c": "Pick a size",
        })
        message = run_check("lang_strings", repo)[0].message
        for expected in ("customize (customise)", "color (colour)", "enrollment (enrolment)", "behavior (behaviour)"):
            self.assertIn(expected, message)
        self.assertNotIn("size", message)

    def test_comments_are_ignored_and_multiline_values_read_whole(self):
        repo = healthy_repo("v/r", "local_x")
        repo._files["lang/en/local_x.php"] = (
            "<?php\n/* $string['z'] = 'Old'; */\n"
            "$string['a'] = 'Colour'; // Replaces color.\n"
            "# $string['a'] = 'Dupe';\n"
            "$string['b'] = 'Semi; colon';\n"
        )
        self.assertEqual(levels(run_check("lang_strings", repo)), [OK])
        repo._files["lang/en/local_x.php"] = "<?php\n$string['a'] = 'Choose a\ncolor' .\n    ' and size';\n"
        self.assertIn("color (colour)", run_check("lang_strings", repo)[0].message)

    def test_activity_modules_drop_the_mod_prefix(self):
        self.assertEqual(lang_file("mod_forum"), "lang/en/forum.php")
        self.assertEqual(levels(run_check("lang_strings", healthy_repo("v/r", "mod_board"))), [OK])


class AmdAndDormantTests(unittest.TestCase):
    def test_amd_builds(self):
        repo = healthy_repo("v/r", "local_x")
        self.assertEqual(run_check("amd_build", repo), [])  # No JavaScript.
        repo._files["amd/src/app.js"] = "define([], function() {});"
        repo._files["amd/src/util.js"] = "define([], function() {});"
        repo._files["amd/build/app.min.js"] = "x"
        repo._files["amd/build/app.min.js.map"] = "x"
        message = run_check("amd_build", repo)[0].message
        self.assertIn("util.min.js", message)
        self.assertIn("util.min.js.map", message)
        repo._files["amd/build/util.min.js"] = repo._files["amd/build/util.min.js.map"] = "x"
        self.assertEqual(levels(run_check("amd_build", repo)), [OK])

    def test_dormant_private_repo_schedules(self):
        cron = CI_YAML.replace("env:", "on:\n  schedule:\n    - cron: '0 3 * * 1'\nenv:")
        dormant = ci_repo(cron, private=True)
        dormant.pushed_at = NOW - timedelta(days=120)
        message = run_check("dormant_actions", dormant)[0].message
        self.assertIn("No push for 120 days", message)
        self.assertIn("Moodle Plugin CI", message)
        quiet = healthy_repo("v/r", "local_x", private=True)
        quiet.pushed_at = NOW - timedelta(days=120)
        self.assertEqual(levels(run_check("dormant_actions", quiet)), [OK])
        quiet._files[".github/dependabot.yml"] = "version: 2\n"
        self.assertIn("Dependabot", run_check("dormant_actions", quiet)[0].message)
        public = ci_repo(cron)
        public.pushed_at = NOW - timedelta(days=120)
        self.assertEqual(run_check("dormant_actions", public), [])
        recent = ci_repo(cron, private=True)
        self.assertEqual(run_check("dormant_actions", recent), [])


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

    def test_run_skips_when_another_run_holds_the_lock(self):
        import fcntl
        os.makedirs(self.cfg["data_dir"], exist_ok=True)
        os.makedirs(self.cfg["www_dir"], exist_ok=True)
        held = open(os.path.join(self.cfg["data_dir"], "run.lock"), "w")
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            status = run(self.cfg, send_alerts=False,
                         sources=[FakeSource(sample_repos())], directory=sample_directory())
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            held.close()
        self.assertFalse(status["run"]["ok"])
        self.assertEqual(status["repos"], [])

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

    def test_dependabot_workflow_is_ignored_by_default(self):
        cfg = config_mod.normalise({})
        self.assertIn("Dependabot Updates", cfg["ci_ignore_workflows"])


class ServeRunTests(unittest.TestCase):
    def test_run_endpoint(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        from plugindash import runserver
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        called = []
        handler = runserver.make_handler({"data_dir": tmp.name}, lambda: called.append(1))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path, method="GET"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)

        status, body = get("/run", method="POST")
        self.assertEqual((status, body.get("started")), (200, True))
        self.assertEqual(called, [1])
        self.assertEqual(get("/healthz")[1], {"ok": True})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            get("/nope")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
