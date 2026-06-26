from __future__ import annotations

import email
import hashlib
import imaplib
import json
import re
from dataclasses import asdict, dataclass, replace
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Callable

from vacancy_monitor.customer_intent import classify_customer_messages
from vacancy_monitor.freelancehunt import FreelancehuntThreadMessage
from vacancy_monitor.order_models import MOSCOW_TZ, Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore


@dataclass(frozen=True)
class EmailInboundMessage:
    message_id: str
    from_email: str
    subject: str
    text: str
    created_at: str | None
    raw: dict

    def as_thread_message(self) -> FreelancehuntThreadMessage:
        return FreelancehuntThreadMessage(
            message_id=self.message_id,
            text=self.text,
            created_at=self.created_at,
            author_id=self.from_email,
            author_type="email",
            is_own=False,
            raw=self.raw,
        )


class IMAPEmailClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        folder: str = "INBOX",
        use_ssl: bool = True,
        timeout_seconds: int = 20,
        imap_factory: Callable[..., object] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds
        self.imap_factory = imap_factory
        self._uid_by_message_id: dict[str, str] = {}

    def list_unseen_messages(self) -> list[EmailInboundMessage]:
        factory = self.imap_factory or (imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4)
        connection = factory(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.login(self.username, self.password)
            connection.select(self.folder)
            status, data = connection.search(None, "UNSEEN")
            if status != "OK" or not data:
                return []
            messages: list[EmailInboundMessage] = []
            for uid in data[0].split():
                fetch_status, payload = connection.fetch(uid, "(BODY.PEEK[])")
                if fetch_status != "OK":
                    continue
                raw_email = _extract_raw_email(payload)
                if raw_email is None:
                    continue
                parsed = parse_email_message(raw_email, uid=uid.decode("utf-8", errors="replace"))
                self._uid_by_message_id[parsed.message_id] = uid.decode("utf-8", errors="replace")
                messages.append(parsed)
            return messages
        finally:
            try:
                connection.logout()
            except Exception:
                pass

    def mark_seen(self, message_id: str) -> None:
        uid = self._uid_by_message_id.get(message_id)
        if not uid:
            return None
        factory = self.imap_factory or (imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4)
        connection = factory(self.host, self.port, timeout=self.timeout_seconds)
        try:
            connection.login(self.username, self.password)
            connection.select(self.folder)
            connection.store(uid.encode("utf-8"), "+FLAGS", "\\Seen")
        finally:
            try:
                connection.logout()
            except Exception:
                pass
        return None


def parse_email_message(raw: bytes, *, uid: str | None = None) -> EmailInboundMessage:
    message = email.message_from_bytes(raw)
    message_id = str(message.get("Message-ID") or uid or "").strip().strip("<>") or _stable_message_id(raw)
    from_email = parseaddr(str(message.get("From") or ""))[1].lower()
    subject = _decode_header(str(message.get("Subject") or ""))
    created_at = _format_email_date(message.get("Date"))
    return EmailInboundMessage(
        message_id=message_id,
        from_email=from_email,
        subject=subject,
        text=_extract_text(message),
        created_at=created_at,
        raw={
            "uid": uid,
            "message_id": message_id,
            "from": from_email,
            "subject": subject,
            "date": str(message.get("Date") or ""),
        },
    )


def find_order_for_email(store: OrderStore, message: EmailInboundMessage) -> Order | None:
    for order in store.list_orders():
        if order.contact and order.contact.channel == "email" and order.contact.value.lower() == message.from_email:
            return order
    return None


def sync_email_messages_to_order(
    *,
    store: OrderStore,
    order: Order,
    messages: list[EmailInboundMessage],
) -> Order:
    order_dir = store.order_dir(order.order_id)
    inbox_dir = order_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    recipient = order.contact.value if order.contact else messages[0].from_email
    payload = {
        "channel": "email",
        "recipient": recipient,
        "messages": [asdict(message) for message in messages],
        "synced_at": format_moscow_time(),
    }
    (inbox_dir / f"email_{_safe_email_slug(recipient)}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_customer_intent(inbox_dir, messages=[message.text for message in messages if message.text])
    _append_email_messages(order_dir / "conversation.md", recipient, messages)

    next_status = OrderStatus.DISCOVERY if order.status == OrderStatus.OUTREACH_SENT else order.status
    updated = replace(order, status=next_status, updated_at=format_moscow_time())
    store.save_order(updated)
    return updated


def build_email_notification(*, order: Order, messages: list[EmailInboundMessage]) -> str:
    latest = next((message for message in reversed(messages) if message.text), None)
    return (
        "Ответ заказчика по email.\n\n"
        f"ID: {order.order_id}\n"
        f"Проект: {order.source_url}\n"
        f"Email: {order.contact.value if order.contact else 'не указан'}\n\n"
        "Последнее сообщение:\n"
        f"{_trim(latest.text if latest else 'Новых сообщений нет.', 1200)}\n\n"
        "Переписка сохранена в папке заказа: conversation.md и inbox/."
    )


def write_email_reply_draft(*, store: OrderStore, order: Order, recipient: str, reply_text: str) -> Path:
    outbox_dir = store.order_dir(order.order_id) / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"email_reply_{_safe_email_slug(recipient)}.md"
    path.write_text(reply_text.strip() + "\n", encoding="utf-8")
    return path


def write_email_reply_sent_record(
    *,
    store: OrderStore,
    order: Order,
    recipient: str,
    reply_text: str,
    response_payload: dict,
) -> Path:
    outbox_dir = store.order_dir(order.order_id) / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"email_reply_{_safe_email_slug(recipient)}.sent.json"
    payload = {
        "channel": "email",
        "recipient": recipient,
        "sent_at": format_moscow_time(),
        "message": reply_text,
        "response": response_payload,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _append_email_messages(path: Path, recipient: str, messages: list[EmailInboundMessage]) -> None:
    if not path.exists():
        path.write_text("# История переписки\n\n", encoding="utf-8")
    existing = path.read_text(encoding="utf-8")
    lines = ["\n\n" f"## Email {recipient}\n\n" f"Обновлено: {format_moscow_time()}\n"]
    for message in messages:
        marker = f"email-message:{message.message_id}"
        if message.message_id and marker in existing:
            continue
        lines.append(
            "\n"
            f"<!-- {marker} -->\n"
            f"### Заказчик"
            f"{' - ' + message.created_at if message.created_at else ''}\n\n"
            f"{message.text or '[пустое сообщение]'}\n"
        )
    if len(lines) > 1:
        with path.open("a", encoding="utf-8") as file:
            file.write("".join(lines))


def _write_customer_intent(inbox_dir: Path, *, messages: list[str]) -> None:
    result = classify_customer_messages(messages)
    payload = {
        "channel": "email",
        "classified_at": format_moscow_time(),
        **result.to_dict(),
    }
    (inbox_dir / "customer_intent.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _extract_text(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return _decode_payload(part)
        for part in message.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                return _html_to_text(_decode_payload(part))
        return ""
    if message.get_content_type() == "text/html":
        return _html_to_text(_decode_payload(message))
    return _decode_payload(message)


def _decode_payload(message: Message) -> str:
    payload = message.get_payload(decode=True)
    if payload is None:
        return str(message.get_payload() or "").strip()
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def _decode_header(value: str) -> str:
    return str(make_header(decode_header(value))).strip()


def _format_email_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")
    except Exception:
        return None


def _extract_raw_email(payload: object) -> bytes | None:
    if not isinstance(payload, list):
        return None
    for item in payload:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _stable_message_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:32]


def _safe_email_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "email"


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
