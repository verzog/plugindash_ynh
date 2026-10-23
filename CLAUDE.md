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

## Behaviours that are easy to get wrong

- `release_match` compares the tag with `version.php` *at that tag*, not on `main`. This avoids a false
  red when `main` is already bumped for the next release.
- A failing Moodle `main` matrix cell, or a GitLab job with `allow_failure`, is amber, never red.

## Layout

```
manifest.toml, config_panel.toml, tests.toml
conf/        nginx.conf, systemd.service (oneshot, sandboxed), systemd.timer
scripts/     _common.sh (all shared logic), install, upgrade, remove, backup, restore, change_url, config
doc/         DESCRIPTION.md, ADMIN.md, POST_INSTALL.md, screenshots/
sources/
  run.py                 entry point (adds its own folder to sys.path)
  plugindash/
    runner.py            one run: collect, history, outputs, alerts
    checks/              one module per check (ID, TITLE, DESCRIPTION, ORDER, run(repo, plugin, ctx))
    sources/             base.py (the RepoView interface), github.py, gitlab.py
    notify/              ntfy.py, mail.py, matrix.py
    phpparse.py, moodle.py, history.py (SQLite), output.py, http.py, config.py
  www/                   static page: index.html, app.js, style.css (reads status.json + history.json)
  tests/                 fakes.py, test_core.py, test_sources.py, make_preview.py
  extensions-example/    copied to $data_dir/extensions on install
```

On the server:

- `/var/www/plugindash/` is `root:www-data 751`; `app/` is `root:plugindash`; `www/` is
  `plugindash:www-data 2750`; `config.json` is mode 600.
- Data lives in `/home/yunohost.app/plugindash/`: `history.sqlite` and `extensions/{checks,notify}`.

Check IDs: `ci_status`, `ci_activity`, `release_match`, `release_zip`, `unreleased`, `issues`,
`moodle_support`, `licence`, `security_alerts`, `plugins_directory`.

## Commands

```bash
cd sources
python3 -m unittest discover -s tests             # Must stay green on python3.11 and python3.13.
python3 tests/make_preview.py /tmp/preview        # Then: cd /tmp/preview/www && python3 -m http.server
bash -n scripts/* && shellcheck -x -e SC1091,SC2154,SC2034 -s bash scripts/*
```

On the server: `sudo systemctl start plugindash.service` runs a check now;
`journalctl -u plugindash.service` shows the logs.

## Test status (v1.0.0~ynh1)

Tested: 42 unit tests on Python 3.11 and 3.13 (every check, GitHub and GitLab sources against a fake API,
alerts on colour change, a rejected token keeping the previous results); scripts dry-run against stand-in
helpers; generated nginx config passed `nginx -t`; `systemd-analyze verify` passed on both units;
shellcheck-clean.

Not yet tested:

- A real YunoHost install, on 12 or 13.
- A run against the real GitHub API.
- `download.moodle.org/api/1.3/pluginfo.php` (may have changed with the Moodle Marketplace move; the check
  downgrades to "info" on any failure).
- The systemd sandbox in a real run. `MemoryDenyWriteExecute` and `ProtectSystem=strict` are the most
  likely to need loosening. If one blocks something, loosen only that option and say why in a comment.
- GitLab against a real instance (only the fake API so far).

## Next tasks

1. Install on the Contabo dev box (YunoHost, Debian 13), add a fine-grained read-only token (Metadata,
   Contents, Issues, Pull requests, Actions, Dependabot alerts), press **Run the check now**.
2. Triage the first real run: false reds/ambers (especially `licence` README parsing and `moodle_support`
   CI matrix detection), API call count, whether `pluginfo.php` still answers.
3. Run `package_check` on YunoHost 12 and 13 if possible.
4. GitLab: verify against the self-hosted instance once it is back.

## Working with Verzog

- Not an experienced coder; strong practical sysadmin and Moodle skills.
- Ask clarifying questions before non-trivial changes. Explain in plain language. Own mistakes openly.
- Australian English, DD/MM/YYYY dates.
- When fixing code, give the whole fixed file, not just the changed lines.
- He likes screenshots of visual changes: re-run `make_preview.py` and screenshot.
