import json
from dataclasses import replace
from datetime import datetime

from vacancy_monitor.models import Post
from vacancy_monitor.order_models import MOSCOW_TZ, OrderStatus, make_order_from_post
from vacancy_monitor.payment_reminder import (
    build_payment_reminder_text,
    load_payment_reminders,
    record_payment_reminder,
    select_due_payment_reminder,
)
from vacancy_monitor.order_store import OrderStore


def _order():
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/bot/123456.html",
            url="https://freelancehunt.com/project/bot/123456.html",
            text="Нужен Telegram-бот, бюджет 15 000 руб.",
            published_at="2026-06-01T10:00:00+03:00",
        ),
        category="Telegram-боты",
        risks=[],
    )
    return replace(
        order,
        status=OrderStatus.PAYMENT_REQUESTED,
        updated_at="25.06.2026 10:00 МСК",
        price_rub=15000,
    )


def _ledger(status="requested"):
    return {
        "current_status": status,
        "events": [
            {
                "event": "payment_requested",
                "status": "requested",
                "created_at": "25.06.2026 10:00 МСК",
            }
        ],
    }


def test_first_payment_reminder_is_due_after_24_hours():
    reminder = select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history={"events": []},
        now=datetime(2026, 6, 26, 10, 1, tzinfo=MOSCOW_TZ),
    )

    assert reminder is not None
    assert reminder.sequence == 1


def test_payment_reminder_is_not_due_before_24_hours():
    reminder = select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history={"events": []},
        now=datetime(2026, 6, 26, 9, 59, tzinfo=MOSCOW_TZ),
    )

    assert reminder is None


def test_second_payment_reminder_waits_48_hours_after_first_send():
    history = {
        "events": [
            {
                "sequence": 1,
                "status": "sent",
                "created_at": "26.06.2026 10:01 МСК",
            }
        ]
    }

    not_due = select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 28, 10, 0, tzinfo=MOSCOW_TZ),
    )
    due = select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 28, 10, 2, tzinfo=MOSCOW_TZ),
    )

    assert not_due is None
    assert due is not None
    assert due.sequence == 2


def test_payment_reminders_stop_after_customer_payment_signal():
    reminder = select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(status="awaiting_confirmation"),
        history={"events": []},
        now=datetime(2026, 6, 30, 10, 0, tzinfo=MOSCOW_TZ),
    )

    assert reminder is None


def test_failed_payment_reminder_retries_hourly_and_stops_after_three_attempts():
    history = {
        "events": [
            {"sequence": 1, "status": "failed", "created_at": "26.06.2026 09:30 МСК"},
        ]
    }

    assert select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 26, 10, 0, tzinfo=MOSCOW_TZ),
    ) is None
    assert select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 26, 10, 31, tzinfo=MOSCOW_TZ),
    ).sequence == 1

    history["events"].extend(
        [
            {"sequence": 1, "status": "failed", "created_at": "26.06.2026 10:31 МСК"},
            {"sequence": 1, "status": "failed", "created_at": "26.06.2026 11:32 МСК"},
        ]
    )
    assert select_due_payment_reminder(
        order=_order(),
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 26, 13, 0, tzinfo=MOSCOW_TZ),
    ) is None


def test_payment_reminder_record_prevents_duplicate_and_formats_message(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = _order()
    store.save_order(order)

    record_payment_reminder(store=store, order=order, sequence=1, status="sent")

    history = load_payment_reminders(store=store, order=order)
    assert history["events"][0]["sequence"] == 1
    assert history["events"][0]["status"] == "sent"
    payload = json.loads(
        (store.order_dir(order.order_id) / "payment" / "reminders.json").read_text(encoding="utf-8")
    )
    assert payload == history
    assert select_due_payment_reminder(
        order=order,
        ledger=_ledger(),
        history=history,
        now=datetime(2026, 6, 26, 11, 0, tzinfo=MOSCOW_TZ),
    ) is None
    text = build_payment_reminder_text(order=order, sequence=1)
    assert "15 000 ₽" in text
    assert "безопасную сделку" in text
