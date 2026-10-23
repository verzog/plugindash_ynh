# Your own checks and alert channels

Files in this folder are loaded by Plugin Dashboard on every run.

- `checks/*.py`: extra checks. A file with the same `ID` as a built-in check replaces it.
- `notify/*.py`: extra alert channels (for example Slack or Discord).

Files ending in anything other than `.py` (like the `.disabled` example) are ignored.
A broken file is logged and skipped; it never stops the daily run.

## A check

```python
from plugindash.model import Finding, OK, INFO, AMBER, RED

ID = "changes_file"                       # Unique, lower-case.
TITLE = "CHANGES.md present"
DESCRIPTION = "Amber if the plugin has no CHANGES.md."   # Shown on the page.

def run(repo, plugin, ctx):
    # repo:   repo.file(path, ref=None), repo.latest_release(), repo.open_issues(),
    #         repo.workflows(), repo.latest_run(wf), repo.html_url, repo.default_branch ...
    # plugin: version.php fields, e.g. plugin["component"], plugin["release"], plugin.get("supported")
    # ctx:    ctx.cfg (settings), ctx.now (UTC), ctx.moodle_latest (e.g. 503)
    if repo.file("CHANGES.md") is None:
        return [Finding(ID, AMBER, "No CHANGES.md", repo.html_url)]
    return [Finding(ID, OK, "CHANGES.md present")]
```

Levels: `RED` (needs fixing), `AMBER` (needs attention), `INFO` (never changes the colour), `OK`.

## An alert channel

```python
ID = "discord"

def configured(cfg):
    return True

def send(cfg, title, body, priority, url):
    from plugindash.http import Client
    Client().request("POST", "https://discord.com/api/webhooks/...", body={"content": f"**{title}**\n{body}"})
```

After adding or changing a file, use **Run the check now** in the app's config panel.
Files here belong to the app user: `sudo chown -R <app>:<app> /home/yunohost.app/<app>/extensions`.
