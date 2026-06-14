from dataclasses import replace
from pathlib import Path

from vacancy_monitor.autopilot import AutopilotResult
from vacancy_monitor.config import Config
from vacancy_monitor.local_agent_cli import (
    handle_order_callback,
    poll_telegram_once,
    poll_telegram_safely,
    run_local_agent_once,
)
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


def safe_autopilot_result() -> AutopilotResult:
    return AutopilotResult(
        safe_to_autopilot=True,
        risk_flags=[],
        summary_ru="Нужен Telegram-бот для заявок.",
        outreach_ru="Здравствуйте! Готов выполнить Telegram-бота для заявок.",
        execution_plan_ru="Собрать бота, подключить Google Sheets, проверить прием заявок.",
        price_rub=12000,
        deadline_ru="2 дня",
        deliverable_markdown="# Черновик результата\n\nСтруктура бота и таблицы подготовлена.",
        customer_message_ru="Здравствуйте! Подготовил план и могу приступить.",
    )


class FakeAutopilotClient:
    def __init__(self, result: AutopilotResult):
        self.result = result
        self.orders = []

    def analyze_order(self, order):
        self.orders.append(order)
        return self.result


class FailingAutopilotClient:
    def analyze_order(self, order):
        raise RuntimeError("provider failed")


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


def test_run_local_agent_records_send_error_without_crashing(tmp_path, capsys):
    config = make_config(tmp_path)
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    def failing_send(text, reply_markup=None):
        raise TimeoutError("telegram timeout for bot123:secret-token")

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=failing_send,
    )

    assert summary.errors == 1
    assert summary.sent == 0
    assert list((tmp_path / "orders").glob("*/state.json"))
    assert "secret-token" not in capsys.readouterr().out

    second_summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
    )

    assert second_summary.checked == 0
    assert second_summary.sent == 0


def test_run_local_agent_draft_mode_writes_autopilot_files_without_status_change(tmp_path):
    sent = []
    config = replace(make_config(tmp_path), auto_mode="draft", openai_api_key="sk-test")
    client = FakeAutopilotClient(safe_autopilot_result())
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=client,
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    order_dir = store.order_dir(order_id)
    assert order.status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert client.orders
    assert (order_dir / "autopilot" / "analysis.json").exists()
    assert (order_dir / "deliverables" / "autopilot_result.md").exists()


def test_run_local_agent_autopilot_mode_moves_safe_order_to_draft_ready(tmp_path):
    sent = []
    config = replace(make_config(tmp_path), auto_mode="autopilot", openai_api_key="sk-test")
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.DRAFT_READY
    assert order.price_rub == 12000


def test_run_local_agent_processes_existing_pending_order_after_restart(tmp_path):
    sent = []
    config = replace(make_config(tmp_path), auto_mode="autopilot", openai_api_key="sk-test")
    store = OrderStore(config.orders_path)
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.DRAFT_READY
    assert (store.order_dir(order.order_id) / "autopilot" / "analysis.json").exists()


def test_run_local_agent_does_not_crash_when_autopilot_error_notification_fails(tmp_path, capsys):
    config = replace(make_config(tmp_path), auto_mode="autopilot", openai_api_key="sk-test")
    store = OrderStore(config.orders_path)
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)

    def failing_send(text, reply_markup=None):
        raise TimeoutError("telegram timeout for bot123:secret-token")

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=failing_send,
        autopilot_client=FailingAutopilotClient(),
    )

    assert summary.errors == 0
    assert store.load_order(order.order_id).status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    output = capsys.readouterr().out
    assert "notification failed: TimeoutError" in output
    assert "secret-token" not in output


def test_run_local_agent_skips_autopilot_without_openai_key(tmp_path):
    sent = []
    config = replace(make_config(tmp_path), auto_mode="draft", openai_api_key=None)
    client = FakeAutopilotClient(safe_autopilot_result())
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=client,
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert client.orders == []
    assert not (store.order_dir(order_id) / "autopilot" / "analysis.json").exists()


def test_poll_telegram_safely_handles_timeout_without_leaking_token(capsys, tmp_path):
    store = OrderStore(tmp_path / "orders")

    def failing_get_updates(token, offset, timeout_seconds):
        raise TimeoutError(f"failed for {token}")

    next_offset = poll_telegram_safely(
        bot_token="bot123:secret-token",
        offset=7,
        timeout_seconds=20,
        store=store,
        get_updates_func=failing_get_updates,
        answer_callback=lambda callback_id, text: None,
    )

    assert next_offset == 7
    output = capsys.readouterr().out
    assert "TimeoutError" in output
    assert "secret-token" not in output


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
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
    )

    assert updated is not None
    assert updated.status == OrderStatus.MANUAL_SEND_NEEDED
    assert answers == ["Готово."]


def test_handle_order_callback_sends_freelancehunt_bid_when_supported(tmp_path):
    answers = []
    sent_orders = []
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
    order_dir = store.order_dir(order.order_id)
    (order_dir / "autopilot").mkdir(parents=True)
    (order_dir / "autopilot" / "outreach.md").write_text(
        "Здравствуйте! Готов выполнить Telegram-бота для заявок.\n",
        encoding="utf-8",
    )

    updated = handle_order_callback(
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
        send_outreach=lambda order, text: sent_orders.append((order.order_id, text)),
    )

    assert updated is not None
    assert updated.status == OrderStatus.OUTREACH_SENT
    assert updated.latest_approved_outreach == "Здравствуйте! Готов выполнить Telegram-бота для заявок."
    assert sent_orders == [(order.order_id, "Здравствуйте! Готов выполнить Telegram-бота для заявок.")]
    assert answers == ["Отклик отправлен через freelancehunt."]


def test_handle_order_callback_falls_back_to_manual_without_outreach_sender(tmp_path):
    answers = []
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

    updated = handle_order_callback(
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
    )

    assert updated is not None
    assert updated.status == OrderStatus.MANUAL_SEND_NEEDED
    assert updated.latest_approved_outreach
    assert answers == ["Готово."]


def test_handle_order_callback_can_send_outreach_from_draft_ready(tmp_path):
    answers = []
    sent_orders = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.DRAFT_READY)
    store.save_order(order)

    updated = handle_order_callback(
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
        send_outreach=lambda order, text: sent_orders.append((order.order_id, text)),
    )

    assert updated is not None
    assert updated.status == OrderStatus.OUTREACH_SENT
    assert sent_orders == [(order.order_id, updated.latest_approved_outreach)]
    assert answers == ["Отклик отправлен через freelancehunt."]


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
        callback_data=f"o:at:{order.order_id}",
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
                "data": f"o:ao:{order.order_id}",
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
