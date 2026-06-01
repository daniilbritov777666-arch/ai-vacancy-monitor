from pathlib import Path

from vacancy_monitor.config import Config
from vacancy_monitor.local_agent_cli import handle_order_callback, poll_telegram_once, run_local_agent_once
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore


def make_config(tmp_path) -> Config:
    return Config(
        bot_token="token",
        chat_id="150761046",
        channels=["sample"],
        rss_feeds=[],
        state_path=tmp_path / "seen_posts.json",
        send_first_run=True,
        orders_path=tmp_path / "orders",
    )


def test_run_local_agent_creates_order_for_new_match(tmp_path):
    sent = []
    config = make_config(tmp_path)
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
    )

    assert summary.sent == 1
    assert list((tmp_path / "orders").glob("*/state.json"))
    assert "Первый отклик" in sent[0][0]


def test_run_local_agent_keeps_first_run_seeding(tmp_path):
    sent = []
    config = Config(
        bot_token="token",
        chat_id="150761046",
        channels=["sample"],
        rss_feeds=[],
        state_path=tmp_path / "seen_posts.json",
        send_first_run=False,
        orders_path=tmp_path / "orders",
    )
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
    )

    assert summary.seeded == 1
    assert summary.sent == 0
    assert sent == []
    assert not Path(config.orders_path).exists()


def test_handle_order_callback_updates_valid_transition(tmp_path):
    answers = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)

    updated = handle_order_callback(
        callback_data=f"order:approve_outreach:{order.order_id}",
        store=store,
        answer=answers.append,
    )

    assert updated is not None
    assert updated.status == OrderStatus.MANUAL_SEND_NEEDED
    assert answers == ["Готово."]


def test_handle_order_callback_rejects_stale_transition(tmp_path):
    answers = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)

    updated = handle_order_callback(
        callback_data=f"order:approve_terms:{order.order_id}",
        store=store,
        answer=answers.append,
    )

    assert updated is None
    assert store.load_order(order.order_id).status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert answers == ["Действие уже неактуально или недоступно."]


def test_poll_telegram_once_handles_callback_updates(tmp_path):
    answers = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)
    updates = [
        {
            "update_id": 100,
            "callback_query": {
                "id": "callback-1",
                "data": f"order:approve_outreach:{order.order_id}",
            },
        }
    ]

    next_offset = poll_telegram_once(
        updates=updates,
        store=store,
        answer_callback=lambda callback_id, text: answers.append((callback_id, text)),
    )

    assert next_offset == 101
    assert store.load_order(order.order_id).status == OrderStatus.MANUAL_SEND_NEEDED
    assert answers == [("callback-1", "Готово.")]
