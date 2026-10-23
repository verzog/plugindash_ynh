"""ntfy push notifications (ntfy.sh or your own ntfy server)."""

from __future__ import annotations

import urllib.parse

from ..http import Client

ID = "ntfy"


def configured(cfg) -> bool:
    return bool(cfg.get("ntfy_url") and cfg.get("ntfy_topic"))


def _header_safe(text: str) -> str:
    """HTTP headers must be latin-1; swap the arrows and dashes we use."""
    return text.replace("→", "->").replace("–", "-").encode("latin-1", "replace").decode("latin-1")


def send(cfg, title, body, priority, url):
    headers = {"Title": _header_safe(title), "Priority": "high" if priority == "high" else "default",
               "Tags": "rotating_light" if priority == "high" else "information_source"}
    if url:
        headers["Click"] = url
    if cfg.get("ntfy_token"):
        headers["Authorization"] = f"Bearer {cfg['ntfy_token']}"
    target = f"{cfg['ntfy_url'].rstrip('/')}/{urllib.parse.quote(cfg['ntfy_topic'], safe='')}"
    Client(timeout=20, retries=1).request("POST", target, body=body, headers=headers)
