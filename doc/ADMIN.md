## Where things are

| What | Where |
|---|---|
| Settings (tokens, schedule, alerts) | Config panel. Saving rebuilds `__INSTALL_DIR__/config.json` |
| Collector code | `__INSTALL_DIR__/app/` |
| Page and generated results | `__INSTALL_DIR__/www/` (`status.json`, `history.json`, `metrics`) |
| History (kept 365 days) | `__DATA_DIR__/history.sqlite` |
| Your own checks and alert channels | `__DATA_DIR__/extensions/` (see the README there) |

Don't edit `config.json` by hand: the config panel overwrites it.

## Running it by hand

```bash
sudo systemctl start __APP__.service                # Same as "Run the check now".
sudo journalctl -u __APP__.service -n 50            # What the last run did.
systemctl list-timers __APP__.timer                 # When the next run is due.
sudo -u __APP__ python3 -I __INSTALL_DIR__/app/run.py --config __INSTALL_DIR__/config.json list-checks
sudo -u __APP__ python3 -I __INSTALL_DIR__/app/run.py --config __INSTALL_DIR__/config.json run --no-alerts
```

## Prometheus

Add a scrape job pointing at `https://__DOMAIN____PATH__/metrics` (path `/metrics` under the dashboard), and add the Prometheus server's address to **Addresses allowed to read /metrics** in the config panel. Over Tailscale/Headscale that is its `100.x.y.z` address. The metrics are:

- `plugindash_repo_status{repo, component, source}`: 0 green, 1 grey, 2 amber, 3 red
- `plugindash_findings{repo, level}`, `plugindash_repos{status}`
- `plugindash_last_run_timestamp_seconds`, `plugindash_last_run_success`, `plugindash_api_calls`

A Grafana alert on `time() - plugindash_last_run_timestamp_seconds > 2*86400` tells you if the daily check stops running.

## Colours

- **Red**: a check found something broken or inconsistent (CI failing on a supported branch, tag ≠ `version.php`, release zip missing, licence mismatch, critical/high security alert).
- **Amber**: needs attention (open issues or PRs, unreleased commits, stale or disabled CI, only the Moodle `main` cell failing, a newer Moodle not supported, directory listing behind).
- **Green**: every check passed.
- **Grey**: archived, or couldn't be read.

To change how serious a check is, add an entry such as `unreleased=info` under **Change how serious a check is**.

## Tokens

- GitHub: fine-grained token, read-only: Metadata, Contents, Issues, Pull requests, Actions, Dependabot alerts. Without Dependabot access the security check just shows "not available".
- GitLab: token with the `read_api` scope.

Tokens are stored in the YunoHost app settings (root only) and in `config.json` (mode 600, readable only by the app's own user). They are never written to the web folder or the logs.
