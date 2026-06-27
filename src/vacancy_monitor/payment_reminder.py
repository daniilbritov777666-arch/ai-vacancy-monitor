from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from vacancy_monitor.order_models import MOSCOW_TZ, Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore


@dataclass(frozen=True)
class PaymentReminder:
    sequence: int
    due_at: datetime


def select_due_payment_reminder(
    *,
    order: Order,
    ledger: dict[str, Any],
    history: dict[str, Any],
    now: datetime | None = None,
) -> PaymentReminder | None:
    if order.status != OrderStatus.PAYMENT_REQUESTED:
        return None
    if ledger.get("current_status") in {"awaiting_confirmation", "confirmed", "completed", "paid"}:
        return None

    current = (now or datetime.now(tz=MOSCOW_TZ)).astimezone(MOSCOW_TZ)
    sent_events = [
        event
        for event in history.get("events", [])
        if event.get("status") == "sent" and event.get("sequence") in {1, 2}
    ]
    sent_sequences = {event["sequence"] for event in sent_events}
    if 2 in sent_sequences:
        return None

    if 1 in sent_sequences:
        first_sent = next(event for event in sent_events if event["sequence"] == 1)
        due_at = _parse_moscow_time(first_sent.get("created_at")) + timedelta(hours=48)
        if current < due_at or not _retry_allowed(history=history, sequence=2, now=current):
            return None
        return PaymentReminder(sequence=2, due_at=due_at)

    requested_at = _payment_requested_at(order=order, ledger=ledger)
    due_at = requested_at + timedelta(hours=24)
    if current < due_at or not _retry_allowed(history=history, sequence=1, now=current):
        return None
    return PaymentReminder(sequence=1, due_at=due_at)


def build_payment_reminder_text(*, order: Order, sequence: int) -> str:
    amount = f"{max(0, int(order.price_rub or 0)):,}".replace(",", " ")
    if order.contact and order.contact.channel == "freelancehunt":
        action = "подтвердить приемку результата и завершить безопасную сделку на Freelancehunt"
    else:
        action = "проверить результат и выполнить оплату по ранее направленным реквизитам"
    prefix = "Напоминаю" if sequence == 1 else "Повторно напоминаю"
    return (
        f"Здравствуйте! {prefix} об оплате выполненного заказа {order.order_id}. "
        f"Сумма: {amount} ₽. Прошу {action}. "
        "Если оплата уже выполнена, сообщите об этом ответным сообщением."
    )


def load_payment_reminders(*, store: OrderStore, order: Order) -> dict[str, Any]:
    path = _reminders_path(store=store, order=order)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("events"), list):
                payload.setdefault("order_id", order.order_id)
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return {"order_id": order.order_id, "events": []}


def record_payment_reminder(
    *,
    store: OrderStore,
    order: Order,
    sequence: int,
    status: str,
    error_type: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    history = load_payment_reminders(store=store, order=order)
    event = {
        "sequence": sequence,
        "status": status,
        "created_at": format_moscow_time(now),
    }
    if error_type:
        event["error_type"] = error_type
    history["events"].append(event)
    path = _reminders_path(store=store, order=order)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return history


def _payment_requested_at(*, order: Order, ledger: dict[str, Any]) -> datetime:
    events = [event for event in ledger.get("events", []) if event.get("event") == "payment_requested"]
    for event in reversed(events):
        if event.get("created_at"):
            return _parse_moscow_time(event["created_at"])
    return _parse_moscow_time(order.updated_at)


def _retry_allowed(*, history: dict[str, Any], sequence: int, now: datetime) -> bool:
    failures = [
        event
        for event in history.get("events", [])
        if event.get("sequence") == sequence and event.get("status") == "failed" and event.get("created_at")
    ]
    if len(failures) >= 3:
        return False
    if not failures:
        return True
    last_failure = max(_parse_moscow_time(event["created_at"]) for event in failures)
    return now >= last_failure + timedelta(hours=1)


def _parse_moscow_time(value: str | None) -> datetime:
    if not value:
        raise ValueError("payment timestamp is required")
    return datetime.strptime(value, "%d.%m.%Y %H:%M МСК").replace(tzinfo=MOSCOW_TZ)


def _reminders_path(*, store: OrderStore, order: Order):
    return store.order_dir(order.order_id) / "payment" / "reminders.json"
