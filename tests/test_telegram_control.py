from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.telegram_control import (
    CallbackAction,
    build_order_keyboard,
    parse_callback_data,
    resolve_transition,
)


def test_parse_callback_data():
    parsed = parse_callback_data("order:approve_outreach:abc123")

    assert parsed.action == CallbackAction.APPROVE_OUTREACH
    assert parsed.order_id == "abc123"


def test_build_order_keyboard_uses_ru_buttons():
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])

    keyboard = build_order_keyboard(order)

    assert keyboard["inline_keyboard"][0][0]["text"] == "Одобрить отклик"
    assert keyboard["inline_keyboard"][0][0]["callback_data"].startswith("order:approve_outreach:")


def test_approve_outreach_requires_waiting_status():
    next_status = resolve_transition(
        action=CallbackAction.APPROVE_OUTREACH,
        current_status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        can_auto_send=False,
    )

    assert next_status == OrderStatus.MANUAL_SEND_NEEDED


def test_approve_outreach_can_auto_send_when_contact_supported():
    next_status = resolve_transition(
        action=CallbackAction.APPROVE_OUTREACH,
        current_status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        can_auto_send=True,
    )

    assert next_status == OrderStatus.OUTREACH_SENT


def test_approve_terms_rejects_stale_status():
    next_status = resolve_transition(
        action=CallbackAction.APPROVE_TERMS,
        current_status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        can_auto_send=False,
    )

    assert next_status is None
