from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from vacancy_monitor.freelancehunt import FreelancehuntThread, FreelancehuntThreadMessage
from vacancy_monitor.order_models import Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore


def find_order_for_thread(store: OrderStore, thread: FreelancehuntThread) -> Order | None:
    if not thread.project_id:
        return None
    for order in store.list_orders():
        if order.contact and order.contact.channel == "freelancehunt" and order.contact.value == thread.project_id:
            return order
        if f"/{thread.project_id}.html" in order.source_url or f"/{thread.project_id}" in order.source_url:
            return order
    return None


def sync_thread_to_order(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    messages: list[FreelancehuntThreadMessage],
) -> Order:
    order_dir = store.order_dir(order.order_id)
    inbox_dir = order_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "thread": thread.raw,
        "messages": [message.raw for message in messages],
        "synced_at": format_moscow_time(),
    }
    (inbox_dir / f"freelancehunt_{thread.thread_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _append_messages(order_dir / "conversation.md", thread, messages)

    next_status = OrderStatus.DISCOVERY if order.status == OrderStatus.OUTREACH_SENT else order.status
    updated = replace(order, status=next_status, updated_at=format_moscow_time())
    store.save_order(updated)
    return updated


def build_thread_notification(
    *,
    order: Order,
    thread: FreelancehuntThread,
    messages: list[FreelancehuntThreadMessage],
) -> str:
    customer_messages = [message for message in messages if not message.is_own and message.text]
    last_message = customer_messages[-1].text if customer_messages else "Новых сообщений нет в ответе API."
    return (
        "Ответ заказчика на Freelancehunt.\n\n"
        f"ID: {order.order_id}\n"
        f"Проект: {order.source_url}\n"
        f"Тред: {thread.thread_id}\n\n"
        "Последнее сообщение:\n"
        f"{_trim(last_message, 1200)}\n\n"
        "Переписка сохранена в папке заказа: conversation.md и inbox/."
    )


def write_thread_reply_draft(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    reply_text: str,
) -> Path:
    outbox_dir = store.order_dir(order.order_id) / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"freelancehunt_reply_{thread.thread_id}.md"
    path.write_text(reply_text.strip() + "\n", encoding="utf-8")
    return path


def write_thread_reply_sent_record(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    reply_text: str,
    response_payload: dict,
) -> Path:
    outbox_dir = store.order_dir(order.order_id) / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"freelancehunt_reply_{thread.thread_id}.sent.json"
    payload = {
        "thread_id": thread.thread_id,
        "project_id": thread.project_id,
        "sent_at": format_moscow_time(),
        "message": reply_text,
        "response": response_payload,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _append_messages(path, thread: FreelancehuntThread, messages: list[FreelancehuntThreadMessage]) -> None:
    if not path.exists():
        path.write_text("# История переписки\n\n", encoding="utf-8")
    existing = path.read_text(encoding="utf-8")
    lines = [
        "\n\n"
        f"## Freelancehunt {thread.thread_id}\n\n"
        f"Обновлено: {thread.updated_at or format_moscow_time()}\n"
    ]
    for message in messages:
        marker = f"freelancehunt-message:{message.message_id}"
        if message.message_id and marker in existing:
            continue
        author = "Мы" if message.is_own else "Заказчик"
        lines.append(
            "\n"
            f"<!-- {marker} -->\n"
            f"### {author}"
            f"{' - ' + message.created_at if message.created_at else ''}\n\n"
            f"{message.text or '[пустое сообщение]'}\n"
        )
    if len(lines) > 1:
        with path.open("a", encoding="utf-8") as file:
            file.write("".join(lines))


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
