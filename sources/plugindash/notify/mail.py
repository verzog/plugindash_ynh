"""Email through the server's own mail system (YunoHost's Postfix on localhost)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

ID = "email"


def configured(cfg) -> bool:
    return bool(cfg.get("email_to"))


def send(cfg, title, body, priority, url):
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = cfg.get("email_from") or "plugindash@localhost"
    msg["To"] = cfg["email_to"]
    if priority == "high":
        msg["X-Priority"] = "1"
    msg.set_content(body + (f"\n\nDashboard: {url}\n" if url else "\n"))
    with smtplib.SMTP(cfg.get("smtp_host", "localhost"), int(cfg.get("smtp_port", 25)), timeout=30) as smtp:
        smtp.send_message(msg)
