from dataclasses import replace
from pathlib import Path

from vacancy_monitor.autopilot import AutopilotResult
from vacancy_monitor.config import Config
from vacancy_monitor.execution import ExecutionDraftPackage
from vacancy_monitor.freelancehunt import FreelancehuntMyBid, FreelancehuntThread, FreelancehuntThreadMessage
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


class FakeConversationReplyClient:
    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls = []

    def draft_thread_reply(self, order, messages):
        self.calls.append((order.order_id, [message.text for message in messages]))
        return self.reply_text


class FakeExecutionDraftClient:
    def __init__(self, *, delivery_message: str = "Здравствуйте! Подготовил рабочий вариант для проверки."):
        self.calls = []
        self.delivery_message = delivery_message

    def draft_execution_package(self, order, conversation_text, execution_context):
        self.calls.append((order.order_id, conversation_text, execution_context))
        return ExecutionDraftPackage(
            summary_ru="Подготовлен рабочий вариант Telegram-бота.",
            files={"bot.py": "print('ready bot')\n"},
            delivery_message_ru=self.delivery_message,
        )


class FailingAutopilotClient:
    def analyze_order(self, order):
        raise RuntimeError("provider failed")


class FakeFreelancehuntConversationClient:
    def __init__(self, *, messages=None, bids=None, unread=True):
        self.marked_read = []
        self.thread_messages = []
        self.messages = messages
        self.bids = bids or []
        self.unread = unread

    def list_threads(self):
        return [
            FreelancehuntThread(
                thread_id="thread-1",
                project_id="123456",
                subject="Telegram bot",
                is_unread=self.unread,
                updated_at="2026-06-15T09:00:00+03:00",
                raw={"id": "thread-1"},
            )
        ]

    def get_thread_messages(self, thread_id):
        return self.messages or [
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

    def mark_thread_read(self, thread_id):
        self.marked_read.append(thread_id)
        return {"data": {"id": thread_id}}

    def add_thread_message(self, *, thread_id, message_html):
        self.thread_messages.append((thread_id, message_html))
        return {"data": {"id": "sent-1", "type": "message"}}

    def list_my_bids(self):
        return self.bids


class FailingBidFreelancehuntClient(FakeFreelancehuntConversationClient):
    def list_my_bids(self):
        error = RuntimeError("bids failed")
        error.response = type("Response", (), {"status_code": 404})()
        raise error


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


def test_run_local_agent_auto_sends_safe_freelancehunt_outreach(tmp_path):
    sent = []
    auto_sent = []
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        auto_outreach_enabled=True,
        channels=[],
        rss_feeds=["https://freelancehunt.com/projects.rss"],
    )
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
        send_outreach=lambda order, text: auto_sent.append((order.contact.value, order.price_rub, text)),
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.OUTREACH_SENT
    assert order.price_rub == 12000
    assert order.latest_approved_outreach == "Здравствуйте! Готов выполнить Telegram-бота для заявок."
    assert auto_sent == [("123456", 12000, "Здравствуйте! Готов выполнить Telegram-бота для заявок.")]
    assert any("Автоотклик отправлен" in message for message, _ in sent)
    assert not any("Новый заказ на подтверждение" in message for message, _ in sent)
    assert all(reply_markup is None for _, reply_markup in sent)


def test_run_local_agent_auto_sends_when_ai_warnings_are_non_blocking(tmp_path):
    auto_sent = []
    result = replace(safe_autopilot_result(), risk_flags=["уточнить формат доступа к Google Sheets"])
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        auto_outreach_enabled=True,
        channels=[],
        rss_feeds=["https://freelancehunt.com/projects.rss"],
    )
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок и Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=FakeAutopilotClient(result),
        send_outreach=lambda order, text: auto_sent.append(order.order_id),
    )

    assert len(auto_sent) == 1


def test_run_local_agent_skips_stale_draft_instead_of_sending_outreach(tmp_path):
    auto_sent = []
    config = replace(
        make_config(tmp_path),
        auto_outreach_enabled=True,
        auto_outreach_max_age_hours=24,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок. Оплата 12 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.DRAFT_READY,
        created_at="01.01.2020 00:00 МСК",
        price_rub=12000,
    )
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        send_outreach=lambda order, text: auto_sent.append(order.order_id),
    )

    assert auto_sent == []
    assert store.load_order(order.order_id).status == OrderStatus.SKIPPED


def test_run_local_agent_syncs_freelancehunt_threads_after_outreach(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.DISCOVERY
    assert conversation_client.marked_read == ["thread-1"]
    assert "Здравствуйте, когда сможете начать?" in (
        store.order_dir(order.order_id) / "conversation.md"
    ).read_text(encoding="utf-8")
    assert any("Ответ заказчика на Freelancehunt" in message for message, _ in sent)


def test_run_local_agent_writes_ai_reply_draft_for_customer_thread(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    reply_client = FakeConversationReplyClient("Здравствуйте! Начать могу сегодня после уточнения доступов.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        conversation_reply_client=reply_client,
    )

    reply_path = store.order_dir(order.order_id) / "outbox" / "freelancehunt_reply_thread-1.md"
    assert "Начать могу сегодня" in reply_path.read_text(encoding="utf-8")
    assert reply_client.calls == [(order.order_id, ["Здравствуйте, когда сможете начать?"])]
    assert any("AI-черновик ответа" in message for message, _ in sent)


def test_run_local_agent_auto_sends_safe_customer_thread_reply(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    reply_client = FakeConversationReplyClient("Здравствуйте! Начать могу сегодня после уточнения доступов.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_reply_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        conversation_reply_client=reply_client,
    )

    assert conversation_client.thread_messages == [
        ("thread-1", "Здравствуйте! Начать могу сегодня после уточнения доступов.")
    ]
    sent_record = store.order_dir(order.order_id) / "outbox" / "freelancehunt_reply_thread-1.sent.json"
    assert sent_record.exists()
    assert any("AI-ответ отправлен заказчику" in message for message, _ in sent)


def test_run_local_agent_blocks_risky_customer_thread_reply(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    reply_client = FakeConversationReplyClient("Пришлите логин и пароль от аккаунта, я все настрою.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_reply_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        conversation_reply_client=reply_client,
    )

    assert conversation_client.thread_messages == []
    assert any("Автоотправка ответа заблокирована" in message for message, _ in sent)


def test_run_local_agent_prepares_execution_workspace_after_customer_reply(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_execution_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    execution_dir = store.order_dir(order.order_id) / "execution"
    assert (execution_dir / "checklist.md").exists()
    assert (execution_dir / "starter" / "bot.py").exists()
    assert any("Рабочий пакет выполнения создан" in message for message, _ in sent)


def test_run_local_agent_generates_execution_draft_after_customer_reply(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeExecutionDraftClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    generated = store.order_dir(order.order_id) / "execution" / "generated" / "bot.py"
    assert "ready bot" in generated.read_text(encoding="utf-8")
    assert (store.order_dir(order.order_id) / "outbox" / "delivery_message.md").exists()
    assert execution_client.calls
    assert any("AI-пакет результата подготовлен" in message for message, _ in sent)


def test_run_local_agent_requests_delivery_approval_after_execution_draft(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeExecutionDraftClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.AWAITING_DELIVERY_APPROVAL
    assert (store.order_dir(order.order_id) / "outbox" / "delivery_approval_requested.json").exists()
    approval_messages = [(message, markup) for message, markup in sent if "Результат готов к проверке" in message]
    assert approval_messages
    assert any(
        button["text"] == "Разрешить отправку"
        for row in approval_messages[-1][1]["inline_keyboard"]
        for button in row
    )


def test_run_local_agent_auto_sends_delivery_after_execution_draft(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeExecutionDraftClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_reply_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        auto_delivery_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.PAYMENT_REQUESTED
    assert ("thread-1", "Здравствуйте! Подготовил рабочий вариант для проверки.") in conversation_client.thread_messages
    assert (store.order_dir(order.order_id) / "outbox" / "delivery_message.sent.json").exists()
    assert not (store.order_dir(order.order_id) / "outbox" / "delivery_approval_requested.json").exists()
    assert any("Результат автоматически отправлен заказчику" in message for message, _ in sent)


def test_run_local_agent_blocks_auto_delivery_when_order_has_risks(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeExecutionDraftClient()
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        auto_delivery_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=["нужно проверить ТЗ"]),
        status=OrderStatus.OUTREACH_SENT,
    )
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.AWAITING_DELIVERY_APPROVAL
    assert conversation_client.thread_messages == []
    assert (store.order_dir(order.order_id) / "outbox" / "delivery_approval_requested.json").exists()
    assert any("Автосдача результата заблокирована" in message for message, _ in sent)


def test_run_local_agent_closes_payment_requested_order_when_winning_project_is_completed(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient(
        unread=False,
        bids=[
            FreelancehuntMyBid(
                bid_id="bid-1",
                project_id="123456",
                status="active",
                is_winner=True,
                project_status="completed",
                raw={"id": "bid-1", "attributes": {"is_winner": True}},
            )
        ],
    )
    config = replace(
        make_config(tmp_path),
        auto_payment_watch_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.PAYMENT_REQUESTED)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.CLOSED
    assert (store.order_dir(order.order_id) / "payment" / "freelancehunt_bid.json").exists()
    assert any("Проект завершен на Freelancehunt" in message for message, _ in sent)


def test_run_local_agent_starts_discovery_when_bid_becomes_winner(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient(
        unread=False,
        bids=[
            FreelancehuntMyBid(
                bid_id="bid-1",
                project_id="123456",
                status="active",
                is_winner=True,
                project_status="in_progress",
                raw={"id": "bid-1"},
            )
        ],
    )
    config = replace(
        make_config(tmp_path),
        auto_payment_watch_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.DISCOVERY
    assert any("Ставка выбрана заказчиком" in message for message, _ in sent)


def test_run_local_agent_records_bid_watcher_error_details(tmp_path):
    sent = []
    conversation_client = FailingBidFreelancehuntClient(unread=False)
    config = replace(
        make_config(tmp_path),
        auto_payment_watch_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    payload = (config.orders_path / "reports" / "freelancehunt_bid_watch_error.json").read_text(encoding="utf-8")
    assert '"status_code": 404' in payload
    assert '"endpoint": "/my/bids"' in payload


def test_run_local_agent_auto_processes_revision_request_after_delivery(tmp_path):
    sent = []
    revision_message = FreelancehuntThreadMessage(
        message_id="msg-revision-1",
        text="Спасибо, нужно поправить текст кнопки и отправить обновленную версию.",
        created_at="2026-06-15T10:00:00+03:00",
        author_id="client-1",
        author_type="employer",
        is_own=False,
        raw={"id": "msg-revision-1"},
    )
    conversation_client = FakeFreelancehuntConversationClient(messages=[revision_message])
    execution_client = FakeExecutionDraftClient(delivery_message="Здравствуйте! Внес правки и отправляю обновленную версию.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_revision_enabled=True,
        auto_delivery_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.PAYMENT_REQUESTED)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED
    assert ("thread-1", "Здравствуйте! Внес правки и отправляю обновленную версию.") in conversation_client.thread_messages
    assert list((store.order_dir(order.order_id) / "revisions").glob("*/delivery_message.sent.json"))
    assert any("Правки автоматически внесены" in message for message, _ in sent)


def test_run_local_agent_blocks_unsafe_revision_request(tmp_path):
    sent = []
    revision_message = FreelancehuntThreadMessage(
        message_id="msg-revision-unsafe",
        text="Поправьте и добавьте обход лимитов API, чтобы работало без ограничений.",
        created_at="2026-06-15T10:00:00+03:00",
        author_id="client-1",
        author_type="employer",
        is_own=False,
        raw={"id": "msg-revision-unsafe"},
    )
    conversation_client = FakeFreelancehuntConversationClient(messages=[revision_message])
    execution_client = FakeExecutionDraftClient(delivery_message="Не должно отправиться.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_revision_enabled=True,
        auto_delivery_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        freelancehunt_api_token="fh-token",
        openai_api_key="sk-test",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.PAYMENT_REQUESTED)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    assert conversation_client.thread_messages == []
    assert execution_client.calls == []
    assert (store.order_dir(order.order_id) / "revisions" / "manual_review_required.json").exists()
    assert any("Автоправка заблокирована" in message for message, _ in sent)


def test_run_local_agent_sends_status_report_with_live_api_audit(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient(
        unread=False,
        bids=[
            FreelancehuntMyBid(
                bid_id="bid-1",
                project_id="123456",
                status="active",
                is_winner=True,
                project_status="in_progress",
                raw={"id": "bid-1", "attributes": {"is_winner": True}},
            )
        ],
    )
    config = replace(
        make_config(tmp_path),
        auto_status_report_enabled=True,
        auto_status_report_interval_minutes=0,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.PAYMENT_REQUESTED)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    reports = [message for message, _ in sent if "Статус агента" in message]
    assert reports
    assert "Треды: 1" in reports[-1]
    assert "Ставки: 1, победившие: 1" in reports[-1]
    assert "Связано с заказами: 2" in reports[-1]
    assert "payment_requested: 1" in reports[-1]
    assert (config.orders_path / "reports" / "freelancehunt_live_api_audit.json").exists()
    assert (config.orders_path / "reports" / "status_report_state.json").exists()


def test_run_local_agent_skips_status_report_until_interval_passes(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient(unread=False)
    config = replace(
        make_config(tmp_path),
        auto_status_report_enabled=True,
        auto_status_report_interval_minutes=360,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    state_dir = config.orders_path / "reports"
    state_dir.mkdir(parents=True)
    (state_dir / "status_report_state.json").write_text('{"sent_at_iso": "2999-01-01T00:00:00+03:00"}\n', encoding="utf-8")

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    assert not any("Статус агента" in message for message, _ in sent)


def test_handle_order_callback_sends_delivery_when_allowed(tmp_path):
    answers = []
    delivered = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.AWAITING_DELIVERY_APPROVAL,
    )
    store.save_order(order)
    outbox = store.order_dir(order.order_id) / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "delivery_message.md").write_text("Здравствуйте! Результат готов к проверке.\n", encoding="utf-8")

    updated = handle_order_callback(
        callback_data=f"o:as:{order.order_id}",
        store=store,
        answer=answers.append,
        send_delivery=lambda order, text: delivered.append((order.order_id, text)),
    )

    assert updated is not None
    assert updated.status == OrderStatus.PAYMENT_REQUESTED
    assert delivered == [(order.order_id, "Здравствуйте! Результат готов к проверке.")]
    assert answers == ["Результат отправлен заказчику."]


def test_poll_telegram_once_routes_delivery_callback(tmp_path):
    answers = []
    delivered = []
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.AWAITING_DELIVERY_APPROVAL,
    )
    store.save_order(order)
    outbox = store.order_dir(order.order_id) / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "delivery_message.md").write_text("Результат готов.\n", encoding="utf-8")

    next_offset = poll_telegram_once(
        updates=[
            {
                "update_id": 100,
                "callback_query": {
                    "id": "callback-1",
                    "data": f"o:as:{order.order_id}",
                },
            }
        ],
        store=store,
        answer_callback=lambda callback_id, text: answers.append((callback_id, text)),
        send_delivery=lambda order, text: delivered.append((order.order_id, text)),
    )

    assert next_offset == 101
    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED
    assert delivered == [(order.order_id, "Результат готов.")]
    assert answers == [("callback-1", "Результат отправлен заказчику.")]


def test_run_local_agent_does_not_auto_send_without_price(tmp_path):
    auto_sent = []
    result = replace(safe_autopilot_result(), price_rub=0)
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        auto_outreach_enabled=True,
        channels=[],
        rss_feeds=["https://freelancehunt.com/projects.rss"],
    )
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, интеграция с Google Sheets. Бюджет обсуждается.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=FakeAutopilotClient(result),
        send_outreach=lambda order, text: auto_sent.append((order.order_id, text)),
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.SKIPPED
    assert auto_sent == []


def test_run_local_agent_does_not_auto_send_when_ai_reports_risks(tmp_path):
    auto_sent = []
    result = replace(
        safe_autopilot_result(),
        safe_to_autopilot=False,
        risk_flags=["нужна узкая экспертиза 1С/WMS"],
    )
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        auto_outreach_enabled=True,
        channels=[],
        rss_feeds=["https://freelancehunt.com/projects.rss"],
    )
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/wms/123456.html",
        url="https://freelancehunt.com/project/wms/123456.html",
        text="Интеграция WMS & 1C - 1000UAH. Нужны доработки интеграции.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=FakeAutopilotClient(result),
        send_outreach=lambda order, text: auto_sent.append((order.order_id, text)),
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.SKIPPED
    assert order.risks == ["нужна узкая экспертиза 1С/WMS"]
    assert auto_sent == []


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


def test_run_local_agent_skips_previously_analyzed_pending_order_in_autopilot(tmp_path):
    config = replace(make_config(tmp_path), auto_mode="autopilot", openai_api_key="sk-test")
    store = OrderStore(config.orders_path)
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот, бюджет обсуждается.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)
    analysis = store.order_dir(order.order_id) / "autopilot" / "analysis.json"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("{}\n", encoding="utf-8")

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
    )

    assert store.load_order(order.order_id).status == OrderStatus.SKIPPED


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
