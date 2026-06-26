from dataclasses import replace

from vacancy_monitor.conversation import (
    build_thread_notification,
    find_order_for_thread,
    sync_thread_to_order,
    write_thread_reply_draft,
)
from vacancy_monitor.customer_intent import CustomerIntent
from vacancy_monitor.freelancehunt import FreelancehuntThread, FreelancehuntThreadMessage
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore


def test_find_order_for_thread_matches_freelancehunt_project_id(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)

    matched = find_order_for_thread(
        store,
        FreelancehuntThread(
            thread_id="thread-1",
            project_id="123456",
            subject="Telegram bot",
            is_unread=True,
            updated_at="2026-06-15T09:00:00+03:00",
            raw={},
        ),
    )

    assert matched == order


def test_sync_thread_to_order_writes_inbox_and_conversation(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)
    thread = FreelancehuntThread(
        thread_id="thread-1",
        project_id="123456",
        subject="Telegram bot",
        is_unread=True,
        updated_at="2026-06-15T09:00:00+03:00",
        raw={"id": "thread-1"},
    )
    messages = [
        FreelancehuntThreadMessage(
            message_id="msg-1",
            text="Здравствуйте, когда сможете начать?",
            created_at="2026-06-15T09:02:00+03:00",
            author_id="client-1",
            author_type="employer",
            is_own=False,
            raw={"id": "msg-1"},
        )
    ]

    sync_thread_to_order(store=store, order=order, thread=thread, messages=messages)

    order_dir = store.order_dir(order.order_id)
    assert (order_dir / "inbox" / "freelancehunt_thread-1.json").exists()
    conversation = (order_dir / "conversation.md").read_text(encoding="utf-8")
    assert "Freelancehunt thread-1" in conversation
    assert "Здравствуйте, когда сможете начать?" in conversation
    assert store.load_order(order.order_id).status == OrderStatus.DISCOVERY
    intent = (order_dir / "inbox" / "customer_intent.json").read_text(encoding="utf-8")
    assert CustomerIntent.REQUIREMENTS_CLARIFICATION.value in intent


def test_build_thread_notification_mentions_customer_message():
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/parser/777.html",
            url="https://freelancehunt.com/project/parser/777.html",
            text="Нужен парсер.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
        risks=[],
    )
    thread = FreelancehuntThread(
        thread_id="thread-9",
        project_id="777",
        subject="Parser",
        is_unread=True,
        updated_at="2026-06-15T09:00:00+03:00",
        raw={},
    )

    text = build_thread_notification(
        order=order,
        thread=thread,
        messages=[
            FreelancehuntThreadMessage(
                message_id="msg-9",
                text="Можете сделать сегодня?",
                created_at="2026-06-15T09:02:00+03:00",
                author_id=None,
                author_type=None,
                is_own=False,
                raw={},
            )
        ],
    )

    assert "Ответ заказчика на Freelancehunt" in text
    assert order.order_id in text
    assert "Можете сделать сегодня?" in text


def test_write_thread_reply_draft_creates_outbox_file(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/parser/777.html",
            url="https://freelancehunt.com/project/parser/777.html",
            text="Нужен парсер.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
        risks=[],
    )
    store.save_order(order)
    thread = FreelancehuntThread(
        thread_id="thread-9",
        project_id="777",
        subject="Parser",
        is_unread=True,
        updated_at="2026-06-15T09:00:00+03:00",
        raw={},
    )

    path = write_thread_reply_draft(
        store=store,
        order=order,
        thread=thread,
        reply_text="Здравствуйте! Начать могу сегодня после уточнения формата данных.",
    )

    assert path.name == "freelancehunt_reply_thread-9.md"
    assert "Начать могу сегодня" in path.read_text(encoding="utf-8")
