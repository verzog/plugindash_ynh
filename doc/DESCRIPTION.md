Plugin Dashboard checks every Moodle plugin repository you own once a day and shows each one as red, amber or green on a single page.

It finds plugins by their `version.php` and checks, for each one:

- **CI**: whether it is passing on the default branch, whether only the Moodle `main` cell is failing, and whether CI has gone quiet or been disabled by GitHub.
- **Releases**: whether the latest tag matches `$plugin->release`, the install zip is attached, and there is merged work not yet released.
- **Moodle versions**: whether a newer stable Moodle is outside `$plugin->supported` or missing from the CI matrix.
- **Licence**: whether the `@license` tag, the `LICENSE` file and the README agree.
- **Housekeeping**: open issues and pull requests, Dependabot security alerts, and whether the Moodle plugins directory listing is behind your latest release.

It can also alert you by ntfy, email or Matrix when a plugin gets a new problem (with what to do about it), and publish metrics for Prometheus/Grafana. You can add your own checks and alert channels as small Python files.

It works with GitHub, and with a self-hosted GitLab.
