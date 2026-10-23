"""Matrix room message (client-server API v3)."""

from __future__ import annotations

import html
import time
import urllib.parse

from ..http import Client

ID = "matrix"


def configured(cfg) -> bool:
    return bool(cfg.get("matrix_homeserver") and cfg.get("matrix_room") and cfg.get("matrix_token"))


def send(cfg, title, body, priority, url):
    room = urllib.parse.quote(cfg["matrix_room"], safe="")
    txn = f"plugindash-{int(time.time() * 1000)}"
    target = f"{cfg['matrix_homeserver'].rstrip('/')}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"
    plain = f"{title}\n\n{body}" + (f"\n\n{url}" if url else "")
    lines = "<br>".join(html.escape(line) for line in body.splitlines())
    link = f'<br><br><a href="{html.escape(url)}">Open dashboard</a>' if url else ""
    payload = {
        "msgtype": "m.text",
        "body": plain,
        "format": "org.matrix.custom.html",
        "formatted_body": f"<strong>{html.escape(title)}</strong><br>{lines}{link}",
    }
    Client(timeout=20, retries=1).request(
        "PUT", target, body=payload, headers={"Authorization": f"Bearer {cfg['matrix_token']}"},
    )
