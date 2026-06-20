from __future__ import annotations

import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from typing import Callable

from vacancy_monitor.order_models import Order


class SMTPOutreachClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        use_ssl: bool = False,
        timeout_seconds: int = 20,
        smtp_factory: Callable[..., object] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds
        self.smtp_factory = smtp_factory

    def send(self, order: Order, text: str) -> None:
        if not order.contact or order.contact.channel != "email":
            raise RuntimeError("order has no email contact")

        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = order.contact.value
        message["Subject"] = f"Отклик на проект: {order.category}"
        message["Message-ID"] = self._message_id(order)
        message.set_content(text)

        context = ssl.create_default_context()
        if self.use_ssl:
            factory = self.smtp_factory or smtplib.SMTP_SSL
            connection = factory(self.host, self.port, timeout=self.timeout_seconds)
        else:
            factory = self.smtp_factory or smtplib.SMTP
            connection = factory(self.host, self.port, timeout=self.timeout_seconds)

        with connection as smtp:
            if not self.use_ssl:
                smtp.starttls(context=context)
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    def _message_id(self, order: Order) -> str:
        digest = hashlib.sha256(order.order_id.encode("utf-8")).hexdigest()[:24]
        domain = self.from_email.rsplit("@", 1)[-1] if "@" in self.from_email else "localhost"
        return f"<{digest}@{domain}>"
