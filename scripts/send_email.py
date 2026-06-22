"""Send email via QQ SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any


def send_qq_email(config: dict[str, Any], subject: str, html_body: str, plain_body: str, timeout: int = 15) -> None:
    smtp_cfg = config.get("smtp", {})
    email_cfg = config.get("email", {})
    sender = smtp_cfg.get("sender", "")
    auth_code = smtp_cfg.get("auth_code", "")
    recipient = smtp_cfg.get("recipient", sender)
    host = smtp_cfg.get("host", "smtp.qq.com")
    port = int(smtp_cfg.get("port", 465))
    sender_name = email_cfg.get("sender_name", "Psychology Literature Daily")
    if not sender or not auth_code:
        raise ValueError("Configure smtp.sender and smtp.auth_code in config.yaml")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = recipient
    msg.attach(MIMEText(plain_body or "Use an HTML-compatible client.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout) as s:
            s.login(sender, auth_code)
            s.sendmail(sender, [recipient], msg.as_string())
    except Exception:
        if port == 465:
            with smtplib.SMTP(host, 587, timeout=timeout) as s:
                s.starttls(context=ctx)
                s.login(sender, auth_code)
                s.sendmail(sender, [recipient], msg.as_string())
        else:
            raise
