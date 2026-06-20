from datetime import datetime, timezone

from vacancy_monitor.models import Post
from vacancy_monitor.order_models import (
    OrderStatus,
    build_order_id,
    format_moscow_time,
    make_order_from_post,
)


def test_format_moscow_time_uses_ru_format():
    value = datetime(2026, 6, 1, 9, 5, tzinfo=timezone.utc)

    assert format_moscow_time(value) == "01.06.2026 12:05 МСК"


def test_build_order_id_is_stable_and_filesystem_safe():
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://example.com/project?id=42",
        url="https://example.com/project?id=42",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    order_id = build_order_id(post)

    assert order_id.startswith("20260601-")
    assert "/" not in order_id
    assert "?" not in order_id


def test_make_order_from_post_uses_ru_defaults():
    post = Post(
        source="sample",
        post_id="sample/10",
        url="https://t.me/sample/10",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    order = make_order_from_post(post, category="Telegram-боты", risks=["уточнить доступы"])

    assert order.status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert order.category == "Telegram-боты"
    assert order.price_rub is None
    assert order.deadline_ru is None
    assert order.risks == ["уточнить доступы"]
    assert order.created_at.endswith("МСК")


def test_make_order_from_freelancehunt_post_enables_api_contact():
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    order = make_order_from_post(post, category="Telegram-боты", risks=[])

    assert order.contact is not None
    assert order.contact.channel == "freelancehunt"
    assert order.contact.value == "123456"
    assert order.contact.can_auto_send is True


def test_make_order_from_public_post_extracts_email_contact():
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:3272",
        url="https://freelance.ru/task/view/3272",
        text="Нужен Telegram-бот. Контакт: client@example.ru",
        published_at="2026-06-20T12:00:00+03:00",
    )

    order = make_order_from_post(post, category="Telegram-боты", risks=[])

    assert order.contact is not None
    assert order.contact.channel == "email"
    assert order.contact.value == "client@example.ru"
    assert order.contact.can_auto_send is True
