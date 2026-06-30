from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Callable


def send_email_payload(
    payload_json: str,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    use_ssl: bool,
    smtp_factory: Callable[..., object] | None = None,
    smtp_ssl_factory: Callable[..., object] | None = None,
) -> None:
    payload = json.loads(payload_json)
    required = {"to", "subject", "text", "message_id"}
    if not required.issubset(payload):
        raise RuntimeError("email bridge payload is incomplete")

    message = EmailMessage()
    message["From"] = from_email
    message["To"] = payload["to"]
    message["Subject"] = payload["subject"]
    message["Message-ID"] = payload["message_id"]
    message.set_content(payload["text"])

    if use_ssl:
        factory = smtp_ssl_factory or smtplib.SMTP_SSL
        connection = factory(host, port, timeout=30)
    else:
        factory = smtp_factory or smtplib.SMTP
        connection = factory(host, port, timeout=30)
    with connection as smtp:
        if not use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def main() -> int:
    send_email_payload(
        os.environ["EMAIL_BRIDGE_PAYLOAD"],
        host=os.environ["SMTP_HOST"],
        port=int(os.environ.get("SMTP_PORT", "465")),
        username=os.environ.get("SMTP_USERNAME", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_email=os.environ["SMTP_FROM"],
        use_ssl=os.environ.get("SMTP_USE_SSL", "true").lower() in {"1", "true", "yes"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
