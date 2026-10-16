"""Email notifications (checkpoint reached, run complete, budget warning, failure) via SMTP.

Credentials come from .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL_TO).
If they are missing, the message is printed instead, so a run never fails because of email.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from . import config


def send(event: str, subject: str, body: str, attachments: list[Path] | None = None) -> bool:
    if event not in config.load("pipeline").get("notify", {}).get("on", []):
        return False
    to = os.environ.get(config.load("pipeline")["notify"].get("email_to_env", "NOTIFY_EMAIL_TO"))
    host, user, pwd = (os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
    if not (to and host and user and pwd):
        print(f"[notify:{event}] {subject}\n{body}\n(email not configured; set SMTP_* in .env)")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"[litreview] {subject}", user, to
    msg.set_content(body)
    for p in attachments or []:
        p = Path(p)
        if p.exists():
            msg.add_attachment(p.read_bytes(), maintype="application", subtype="octet-stream",
                               filename=p.name)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587))) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True
