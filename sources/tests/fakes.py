"""In-memory stand-ins for GitHub/GitLab, used by the tests and the sample-data preview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugindash.model import Job, NotAvailable, Release, Run, SecurityAlert, Workflow
from plugindash.sources.base import RepoView, Source

NOW = datetime(2026, 10, 23, 0, 30, tzinfo=timezone.utc)

GPL_HEADER = "// This file is part of Moodle - https://moodle.org/\n"
GPL_TAG = "http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later"
SCCA_TAG = "Proprietary — Skin Cancer College Australasia, all rights reserved"
GPL3_TEXT = "                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n"
MIT_TEXT = "MIT License\n\nCopyright (c) 2024\n\nPermission is hereby granted, free of charge, ...\n"
GITATTRIBUTES = "* text=auto eol=lf\n/.github export-ignore\n/tests export-ignore\n/.gitattributes export-ignore\n"
SCCA_PHPCS = '<ruleset name="P"><rule ref="moodle"><exclude name="moodle.Files.BoilerplateComment"/></rule></ruleset>\n'
CI_YAML = """
env:
  TZ: Australia/Sydney
jobs:
  test:
    continue-on-error: ${{ matrix.moodle-branch == 'main' }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - {moodle-branch: 'MOODLE_501_STABLE', php: '8.2', database: 'pgsql'}
          - {moodle-branch: 'MOODLE_502_STABLE', php: '8.3', database: 'pgsql'}
          - {moodle-branch: 'MOODLE_503_STABLE', php: '8.4', database: 'mariadb'}
          - {moodle-branch: 'main', php: '8.4', database: 'pgsql'}  # Next version; allowed to fail.
    steps:
      - name: PHP Code Sniffer
        run: moodle-plugin-ci phpcs --max-warnings 0
      - name: PHPDoc checker
        run: moodle-plugin-ci phpdoc --max-warnings 0
      - name: Grunt
        if: ${{ !cancelled() && matrix.moodle-branch == 'MOODLE_501_STABLE' }}
        run: moodle-plugin-ci grunt --max-lint-warnings 0
      - name: PHPUnit tests
        run: moodle-plugin-ci phpunit --fail-on-warning
      - name: Behat features
        run: moodle-plugin-ci behat --auto-rerun 3
"""


def version_php(component, release, version=2026100100, supported="[501, 503]", license_tag=GPL_TAG,
                requires=2025100600, copyright=None):
    if copyright is None:
        copyright = "© Skin Cancer College Australasia" if license_tag == SCCA_TAG else "2026 Vernon Spain"
    supported_line = f"$plugin->supported = {supported};\n" if supported else ""
    requires_line = f"$plugin->requires = {requires};\n" if requires else ""
    return (
        "<?php\n" + GPL_HEADER +
        "/**\n * Version details.\n *\n"
        f" * @package    {component}\n * @copyright  {copyright}\n * @license    {license_tag}\n */\n\n"
        "defined('MOODLE_INTERNAL') || die();\n\n"
        f"$plugin->component = '{component}'; // Full name.\n"
        f"$plugin->version = {version};\n"
        f"$plugin->release = '{release}';\n"
        f"{requires_line}{supported_line}"
        "$plugin->maturity = MATURITY_STABLE;\n"
    )


class FakeRepo(RepoView):
    source = "github"

    def __init__(self, full_name, files=None, tag_files=None, release=None, commits_since=0, issues=0, prs=0,
                 workflows=None, runs=None, jobs=None, alerts=None, archived=False, fork=False, private=False,
                 source="github"):
        super().__init__()
        self.source = source
        self.full_name = full_name
        self.name = full_name.split("/")[-1]
        self.html_url = f"https://github.com/{full_name}"
        self.archived, self.fork, self.private = archived, fork, private
        self.pushed_at = NOW - timedelta(days=3)
        self._files = files or {}
        self._tag_files = tag_files or {}
        self._release = release
        self._commits = commits_since
        self._issues, self._prs = issues, prs
        self._workflows = workflows if workflows is not None else [
            Workflow("1", "Moodle Plugin CI", ".github/workflows/moodle-ci.yml", "active"),
            Workflow("2", "Release zip", ".github/workflows/release.yml", "active"),
        ]
        self._runs = runs or {}
        self._jobs = jobs or {}
        self._alerts = alerts
        self.calls = 0

    def file(self, path, ref=None):
        self.calls += 1
        if ref and ref != self.default_branch:
            return self._tag_files.get(ref, {}).get(path)
        return self._files.get(path)

    def list_dir(self, path):
        prefix = path.rstrip("/") + "/"
        names = [p[len(prefix):] for p in self._files if p.startswith(prefix) and "/" not in p[len(prefix):]]
        return names or None

    def file_url(self, path, ref=None):
        return f"{self.html_url}/blob/{ref or self.default_branch}/{path}"

    def latest_release(self):
        return self._release

    def previous_release(self):
        return getattr(self, "_previous", None)

    def commits_since(self, tag):
        return self._commits

    def compare_url(self, tag):
        return f"{self.html_url}/compare/{tag}...main"

    def open_issues(self):
        return [{"number": i} for i in range(self._issues)]

    def open_pull_requests(self):
        return [{"number": i, "pull_request": {}} for i in range(self._prs)]

    def issues_url(self):
        return f"{self.html_url}/issues"

    def pulls_url(self):
        return f"{self.html_url}/pulls"

    def workflows(self):
        return self._workflows

    def latest_run(self, workflow):
        return self._runs.get(workflow.id)

    def run_jobs(self, run):
        return self._jobs.get(run.id, [])

    def security_alerts(self):
        if self._alerts is None:
            raise NotAvailable("Dependabot alerts are off for this repo")
        return self._alerts

    def security_url(self):
        return f"{self.html_url}/security/dependabot"


class DeniedRepo(FakeRepo):
    """A repo the token can list but whose files it can't read (no Contents permission)."""

    def file(self, path, ref=None):
        from plugindash.http import AuthError
        raise AuthError(403, f"https://api.github.com/repos/{self.full_name}/contents/{path}", "")


def denied_repo(full_name):
    return DeniedRepo(full_name)


class FakeSource(Source):
    name = "github"

    def __init__(self, repos, latest_branch=503):
        self.repos = repos
        self.latest = latest_branch

    def list_repos(self):
        return self.repos

    def moodle_latest_branch(self):
        return self.latest


class FakeDirectory:
    def __init__(self, listings=None, fail=False):
        self.listings = listings or {}
        self.fail = fail

        class _C:
            calls = 0
        self.client = _C()

    def lookup(self, component, branch):
        if self.fail:
            from plugindash.http import HttpError
            raise HttpError(0, "https://download.moodle.org", "unreachable")
        return self.listings.get(component)


def ok_run(run_id="r1", days_ago=2):
    return Run(run_id, "success", NOW - timedelta(days=days_ago), f"https://github.com/x/actions/runs/{run_id}")


def failed_run(run_id="r1", days_ago=1):
    return Run(run_id, "failure", NOW - timedelta(days=days_ago), f"https://github.com/x/actions/runs/{run_id}")


def release(tag, component, assets=True, days_ago=20):
    names = [f"{component}-{tag}.zip"] if assets else []
    return Release(tag, tag, f"https://github.com/x/releases/tag/{tag}", NOW - timedelta(days=days_ago),
                   [{"name": n, "url": f"https://example/{n}"} for n in names])


def lang_file_text(component, strings=None):
    strings = strings or {"pluginname": component, "privacy:metadata": "Stores no personal data."}
    return "<?php\n" + "".join(f"$string['{k}'] = '{v}';\n" for k, v in strings.items())


def healthy_repo(full_name, component, rel="1.3.0", version=2026100100, **overrides):
    files = {
        "version.php": version_php(component, rel, version),
        "LICENSE": GPL3_TEXT,
        "README.md": f"# {component}\n\n## License\n\nGNU GPL v3 or later.\n",
        ".github/workflows/moodle-ci.yml": CI_YAML,
        ".gitattributes": GITATTRIBUTES,
        "classes/privacy/provider.php": "<?php\n",
        f"lang/en/{component[4:] if component.startswith('mod_') else component}.php": lang_file_text(component),
    }
    tag = f"v{rel}"
    params = dict(
        files=files,
        tag_files={tag: {"version.php": version_php(component, rel, version)}},
        release=release(tag, component),
        runs={"1": ok_run()},
        jobs={"r1": [Job("test (MOODLE_503_STABLE, 8.4, pgsql)", "success")]},
        alerts=[],
    )
    params.update(overrides)
    return FakeRepo(full_name, **params)


def sample_repos():
    """A realistic mix for the preview: every colour and most findings."""
    repos = []
    repos.append(healthy_repo("verzog/moodle-datafield_gradeentry", "datafield_gradeentry", "2.1.0"))
    repos.append(healthy_repo("verzog/moodle-block_servermon", "block_servermon", "1.9.0"))
    repos.append(healthy_repo("verzog/moodle-tool_pluginstash", "tool_pluginstash", "1.0.0"))

    # Red: CI failing for real.
    r = healthy_repo("verzog/moodle-tool_automate", "tool_automate", "0.9.2", issues=3)
    r._runs = {"1": failed_run("r9")}
    r._jobs = {"r9": [Job("test (MOODLE_503_STABLE, 8.4, mariadb)", "failure"),
                      Job("test (main, 8.4, pgsql)", "failure")]}
    repos.append(r)

    # Red: release zip missing + tag mismatch.
    r = healthy_repo("verzog/moodle-local_lessonimportpptx", "local_lessonimportpptx", "1.2.0")
    r._release = release("v1.2.0", "local_lessonimportpptx", assets=False)
    r._tag_files = {"v1.2.0": {"version.php": version_php("local_lessonimportpptx", "1.1.9")}}
    repos.append(r)

    # Amber: only the Moodle main cell failing, plus unreleased commits.
    r = healthy_repo("verzog/moodle-tiny_bootstrap", "tiny_bootstrap", "1.4.1", commits_since=6)
    r._runs = {"1": failed_run("r5")}
    r._jobs = {"r5": [Job("test (main, 8.4, pgsql)", "failure"), Job("test (MOODLE_503_STABLE, 8.3, pgsql)", "success")]}
    repos.append(r)

    # Amber: workflow disabled by GitHub, open PR.
    r = healthy_repo("verzog/moodle-local_grpcalendarimport", "local_grpcalendarimport", "1.1.0", prs=1)
    r._workflows = [Workflow("1", "Moodle Plugin CI", ".github/workflows/moodle-ci.yml", "disabled_inactivity")]
    r._runs = {}
    repos.append(r)

    # Amber: supported range stops before the newest Moodle (5.3), directory listing behind.
    r = healthy_repo("verzog/moodle-local_freshdesk", "local_freshdesk", "2.0.1")
    r._files["version.php"] = version_php("local_freshdesk", "2.0.1", supported="[501, 502]")
    repos.append(r)

    # Red: LICENSE file says MIT while version.php says GPL; medium Dependabot alert.
    r = healthy_repo("verzog/moodle-tool_canvasuplifter", "tool_canvasuplifter", "0.4.0", issues=1)
    r._files["LICENSE"] = MIT_TEXT
    r._alerts = [SecurityAlert("medium", "phpmailer: header injection")]
    repos.append(r)

    # Mode A (proprietary, private): no Dependabot, not in the directory.
    r = healthy_repo("verzog/moodle-tool_imageextractor", "tool_imageextractor", "0.13.0", private=True,
                     alerts=None)
    r._files["version.php"] = version_php("tool_imageextractor", "0.13.0", license_tag=SCCA_TAG)
    r._tag_files["v0.13.0"]["version.php"] = r._files["version.php"]
    r._files["LICENSE"] = "Copyright (c) Skin Cancer College Australasia.\nAll rights reserved.\n"
    r._files["README.md"] = "# Image extractor\n\n## Licence\n\nProprietary. All rights reserved.\n"
    r._files[".phpcs.xml"] = SCCA_PHPCS
    repos.append(r)

    # Grey: archived.
    repos.append(healthy_repo("verzog/moodle-local_scca_pwa", "local_scca_pwa", "1.0.0", archived=True))

    # Not a Moodle plugin: must be ignored.
    repos.append(FakeRepo("verzog/flood-watcher", files={"README.md": "# Flood Watcher"}))
    return repos


def sample_directory():
    return FakeDirectory({
        "datafield_gradeentry": {"name": "Grade entry", "version": 2026100100, "release": "2.1.0",
                                 "url": "https://moodle.org/plugins/datafield_gradeentry"},
        "block_servermon": {"name": "Server monitor", "version": 2026100100, "release": "1.9.0",
                            "url": "https://moodle.org/plugins/block_servermon"},
        "local_freshdesk": {"name": "Freshdesk", "version": 2026010100, "release": "1.8.0",
                            "url": "https://moodle.org/plugins/local_freshdesk"},
    })
