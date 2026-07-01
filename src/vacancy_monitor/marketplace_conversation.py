from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from vacancy_monitor.order_models import format_moscow_time


@dataclass(frozen=True)
class MarketplaceMessage:
    message_id: str | None
    author: str
    text: str
    created_at: str | None


def sync_marketplace_messages(
    *,
    order_dir: Path,
    channel: str,
    messages: list[MarketplaceMessage],
) -> list[MarketplaceMessage]:
    inbox_dir = order_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    new_messages = []
    for message in messages:
        key = _message_key(channel=channel, message=message)
        path = inbox_dir / f"platform_{key}.json"
        if path.exists():
            continue
        payload = {"channel": channel, **asdict(message)}
        _write_json_atomic(path, payload)
        _append_conversation(order_dir=order_dir, channel=channel, message=message)
        new_messages.append(message)
    return new_messages


def write_marketplace_reply_draft(*, order_dir: Path, channel: str, reply_text: str) -> Path:
    outbox_dir = order_dir / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"platform_reply_{_slug(channel)}.md"
    path.write_text(reply_text.strip() + "\n", encoding="utf-8")
    return path


def write_marketplace_reply_sent_record(
    *,
    order_dir: Path,
    channel: str,
    reply_text: str,
    reference: str | None,
) -> Path:
    outbox_dir = order_dir / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"platform_reply_{_slug(channel)}.sent.json"
    _write_json_atomic(
        path,
        {
            "sent_at": format_moscow_time(),
            "channel": channel,
            "message": reply_text.strip(),
            "reference": reference,
        },
    )
    return path


def _message_key(*, channel: str, message: MarketplaceMessage) -> str:
    identity = message.message_id or "\x1f".join(
        (channel, message.author, message.text, message.created_at or "")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _append_conversation(*, order_dir: Path, channel: str, message: MarketplaceMessage) -> None:
    path = order_dir / "conversation.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    author = "Заказчик" if message.author == "customer" else "Исполнитель"
    timestamp = message.created_at or format_moscow_time()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {author} ({channel}, {timestamp})\n\n{message.text.strip()}\n")


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_") or "marketplace"


def _write_json_atomic(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
