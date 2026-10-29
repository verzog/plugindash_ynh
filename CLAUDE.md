# Plugin Dashboard (plugindash_ynh)

A YunoHost app that checks all of Verzog's Moodle plugin repositories once a day and shows each one as
red, amber, green or grey on a single page. It is for his own use only: one admin user, behind YunoHost SSO.

- App id: `plugindash`. Licence: GPL-3.0-or-later, © 2026 Vernon Spain.
- The global CLAUDE.md is about Moodle plugins (phpcs, licence modes, CI matrix). Its PHP and Moodle rules
  don't apply to this Python/YunoHost app. The general ones still do: no secrets in commits, one concern
  per PR, branch from `main`.

## Decisions already made (don't revisit without asking)

- Packaging v2, helpers 2.1, `yunohost >= 12.1.17`. Must work on YunoHost 12 (Bookworm) and 13 (Trixie).
- The collector is Python with the standard library only: no venv, no pip. It runs as `python3 -I -B run.py`.
- Plugins are detected automatically: any repo with a `version.php` containing `$plugin->component`.
  The config panel has an exclude list.
- An open issue (or PR) makes a plugin amber.
- `version.php` is parsed as text and never executed. Anything read from a repo is untrusted data.
- Personal app: it will not be submitted to the YunoHost catalogue. So the app code stays inside the
  package (`sources/`), and linter warnings that only matter for the catalogue (README not generated,
  not in the catalogue, no category) can be ignored.
- Known package_linter false positives: `icon` on config panel buttons (core supports it; the schema
  lags) and the systemd "harden the security" notice (the linter's regex wants leading whitespace).
- Runs once a day on a systemd timer, 06:30 by default, Australia/Brisbane. Both are set in the config panel.
- Alerts go out when a plugin gets worse (default; configurable). Channels: ntfy, email (local Postfix),
  Matrix. The first run never alerts.
- `/metrics` is let through SSOwat (permission `metrics`, visitors, protected) and limited by IP in nginx
  (setting `metrics_allow`).
- Tokens are stored only in YunoHost settings and in `config.json` (mode 600, owned by the app user).
  Never write them into the web folder or the logs.
- "Run check now" on the page POSTs to `__PATH__/run`, which nginx proxies (behind the admin SSO) to a
  localhost-only service, `plugindash-run` (`runserver.py`, port from `[resources.ports]`). It starts a
  detached collector run. Runs are serialised by `$data_dir/run.lock`, so it never overlaps the timer.
- "No published releases yet" is info, not amber: an unreleased plugin isn't unhealthy.
- GitHub's own "Dependabot Updates" workflow is never plugin CI (ignored by default).

## Behaviours that are easy to get wrong

- `release_match` compares the tag with `version.php` *at that tag*, not on `main`. This avoids a false
  red when `main` is already bumped for the next release.
- A failing Moodle `main` matrix cell, or a GitLab job with `allow_failure`, is amber, never red.
- Grey means "not checked": archived (page label "Archived") *or* unreadable (label "Unreadable"). A repo
  the token can't read is shown grey with a hint (GitHub: Contents; GitLab: read_api), never dropped.
  If no repo at all could be read, the run fails and the previous results stay on screen.
- A check that couldn't run because of the token (403, or a 404 reaching a check, which is how GitHub
  hides private-repo data from a token without that permission) is amber with `overridable=False`, so a
  severity override can't make it look healthy. Other fetch errors (5xx, network) stay info, so a brief
  outage doesn't flip colours. Missing Dependabot access is `NotAvailable` and stays info.
- Expected 404s (missing file, no release, no workflows) are turned into empty results inside the
  sources. Without Contents, GitHub reports a private repo's `version.php` as 404 too, so such a repo
  looks like a non-plugin and is skipped: a known limit no code can tell apart.
- A custom check returning a bad level becomes a "check error" for that check only; the run carries on.
- Every red/amber finding carries a `fix` ("What to do"). Checks hold their advice in a `FIX` table: the first
  key found in the message wins, `""` is the default; the runner fills it in (`checks.fix_for`). A test fails
  if a key matches nothing in its check, or a sample problem has no fix.
- Alerts compare against the `alert_baseline` table (colours you were last told about), not the last
  run. If every channel fails, changed repos keep their old baseline colour, so the alert is resent
  next run. With no channel set up, `alert_on = none` or `--no-alerts`, the baseline just moves on.
- The config panel's `tags` widget splits on spaces. Settings that can hold multi-word values (e.g.
  `ci_ignore_workflows`) must be plain `string` fields, comma-separated.
- GitHub owners may be entered as a profile URL or `@handle`; they're normalised to the bare login.

## Layout

```
manifest.toml, config_panel.toml, tests.toml
conf/        nginx.conf, systemd.service (oneshot, sandboxed), systemd.timer,
             systemd-run.service (the localhost "Run check now" endpoint)
scripts/     _common.sh (all shared logic), install, upgrade, remove, backup, restore, change_url, config
doc/         DESCRIPTION.md, ADMIN.md, POST_INSTALL.md, logo.svg, logo.png, screenshots/
sources/
  run.py                 entry point (adds its own folder to sys.path)
  plugindash/
    runner.py            one run: collect, history, outputs, alerts (guarded by run.lock)
    runserver.py         localhost-only POST /run endpoint behind the "Run check now" button
    checks/              one module per check (ID, TITLE, DESCRIPTION, ORDER, run(repo, plugin, ctx))
    sources/             base.py (the RepoView interface), github.py, gitlab.py
    notify/              ntfy.py, mail.py, matrix.py
    phpparse.py, moodle.py, history.py (SQLite: runs, statuses, alert_baseline), output.py, http.py, config.py
  www/                   static page: index.html, app.js, style.css, favicon.svg (reads status.json +
                         history.json; also Export CSV / Export PDF and Run check now)
  tests/                 fakes.py, test_core.py, test_sources.py, make_preview.py
  extensions-example/    copied to $data_dir/extensions on install
```

On the server:

- `/var/www/plugindash/` is `root:www-data 751`; `app/` is `root:plugindash`; `www/` is
  `plugindash:www-data 2750`; `config.json` is mode 600.
- Data lives in `/home/yunohost.app/plugindash/`: `history.sqlite`, `run.lock` and `extensions/{checks,notify}`.
- Units: `plugindash.timer` → `plugindash.service` (the daily run), and `plugindash-run.service` (always on).

Check IDs: `ci_status`, `ci_activity`, `release_match`, `release_zip`, `unreleased`, `issues`,
`moodle_support`, `moodle_baseline`, `ci_setup`, `licence`, `licence_mode`, `repo_files`, `lang_strings`,
`amd_build`, `security_alerts`, `plugins_directory`, `dormant_actions`.

`moodle_baseline` and `ci_setup` hold plugins to the conventions in Verzog's Moodle plugin CLAUDE.md. The
supported range is two config panel settings, `moodle_min_branch` / `moodle_max_branch` ("5.1" / "5.3"),
parsed to 501 / 503. Workflows are read with plain text matching (`checks/_ci.py`, no YAML library):
flow or block `include:` matrices and cross-product matrices (with `exclude:`, the PHP rule is skipped).
`moodle.py` holds the facts: `BRANCH_VERSIONS` (only certain values) and `min_php()` (5.2 dropped 8.2).
GitLab repos only get the TZ and warning-flag rules.

`repo_files` checks the boilerplate sniff against the mode (SCCA must exclude it, red; GPL must keep it,
amber), the `@copyright` holder (skipped for forks), `.gitattributes` and `classes/privacy/provider.php`.
`lang_strings` reads `lang/en/<component>.php` (`mod_` plugins drop the prefix): C-order keys, no repeats,
and a fixed list of US spellings (whole words; `-ize` stems listed one by one, so "size" isn't caught).
`amd_build` compares `amd/src` with `amd/build` via `RepoView.list_dir()` (it can't tell a stale build,
only a missing one). `dormant_actions` only looks at private GitHub repos idle for 90+ days.

Licence modes (`modes.py`, from the `@license` tag; shown as a tag on each row):

- **SCCA (Mode A)**, in-house, never distributed: a public repo is red; a plugins directory listing is red;
  a missing or misnamed release zip and unreleased commits are info; tag vs `version.php` still checked.
- **GPL (Mode B)**, distributed: the full release rules.
- Anything else ("Proprietary", "Other licence", "No licence") gets the Mode B rules and an info note.

## Commands

```bash
cd sources
python3 -m unittest discover -s tests             # Must stay green on python3.11 and python3.13.
python3 tests/make_preview.py /tmp/preview        # Then: cd /tmp/preview/www && python3 -m http.server
bash -n scripts/* && shellcheck -x -e SC1091,SC2154,SC2034 -s bash scripts/*
```

On the server: `sudo systemctl start plugindash.service` runs a check now;
`journalctl -u plugindash.service` shows the logs (`-u plugindash-run.service` for the run-now endpoint).

## Versions and upgrades

The app is installed, so every change that should reach the server needs a version bump in
`manifest.toml` (`1.2.0~ynh1` → `1.2.1~ynh1` for app code, `~ynh2` for packaging-only changes), or
`yunohost app upgrade` won't see it. Parallel PRs need distinct versions.

## Test status (v1.2.0~ynh1)

Tested: 58 unit tests on Python 3.11 and 3.13 (every check, GitHub and GitLab sources against a fake API,
alerts and alert retries, unreadable repos, permission-blocked checks, the run lock and run endpoint).
The generated nginx config (before the `/run` route was added) ran in nginx with headers-more.
Shellcheck-clean; package_linter clean apart from the known false positives and catalogue warnings.
Installed and run against the real GitHub API; the first real run was triaged in PR #11 (owner URL,
release tag message, Dependabot workflow).

Not yet confirmed:

- YunoHost 12 (Bookworm), and `package_check` on either version.
- Whether `download.moodle.org/api/1.3/pluginfo.php` still answers (the check downgrades to "info" on any
  failure).
- The systemd sandbox for the alert channels. If an option blocks something, loosen only that option and
  say why in a comment.
- GitLab against a real instance (only the fake API so far).

## Next tasks

1. Check whether `pluginfo.php` still answers; run `package_check` if possible.
2. GitLab: verify against the self-hosted instance once it is back.

## Working with Verzog

- Not an experienced coder; strong practical sysadmin and Moodle skills.
- Ask clarifying questions before non-trivial changes. Explain in plain language. Own mistakes openly.
- Australian English, DD/MM/YYYY dates.
- When fixing code, give the whole fixed file, not just the changed lines.
- He likes screenshots of visual changes: re-run `make_preview.py` and screenshot.
