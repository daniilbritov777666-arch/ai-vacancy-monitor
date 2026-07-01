import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import requests
import vacancy_monitor.local_agent_cli as local_agent_cli

from vacancy_monitor.autopilot import AutopilotResult
from vacancy_monitor.config import Config
from vacancy_monitor.execution import ExecutionDraftPackage
from vacancy_monitor.execution_verifier import (
    CommandResult,
    ExecutionVerificationReport,
    ProjectType,
    VerificationIssue,
    VerificationStatus,
)
from vacancy_monitor.email_inbound import EmailInboundMessage
from vacancy_monitor.email_transport_health import EmailTransportHealth
from vacancy_monitor.freelancehunt import FreelancehuntMyBid, FreelancehuntThread, FreelancehuntThreadMessage
from vacancy_monitor.local_agent_cli import (
    _process_agent_jobs,
    handle_order_callback,
    poll_telegram_once,
    poll_telegram_safely,
    run_local_agent_once,
)
from vacancy_monitor.job_queue import AgentJobQueue, JobStatus
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import CustomerContact, OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import load_payment_ledger
from vacancy_monitor.payment_reminder import load_payment_reminders
from vacancy_monitor.quality import AIQualityReview
from vacancy_monitor.public_sources import PublicSourceHealth


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


def test_run_local_agent_writes_public_source_health_report(tmp_path):
    config = replace(
        make_config(tmp_path),
        public_project_sources=["freelance_ru", "pchel"],
        public_source_probes=["kwork", "workzilla"],
        send_first_run=False,
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=lambda source: [],
        probe_public=lambda source: PublicSourceHealth(
            source=source,
            url=f"https://example.com/{source}",
            checked_at="2026-06-20T18:00:00+03:00",
            status="available",
        ),
        send_message=lambda text, reply_markup=None: None,
    )

    report = json.loads(
        (config.orders_path / "reports" / "public_sources_health.json").read_text(encoding="utf-8")
    )
    assert [item["source"] for item in report["sources"]] == [
        "freelance_ru",
        "pchel",
        "kwork",
        "workzilla",
    ]


def test_run_local_agent_uses_freelancehunt_api_instead_of_its_rss(tmp_path):
    config = replace(
        make_config(tmp_path),
        channels=[],
        rss_feeds=[
            "https://freelancehunt.com/projects.rss",
            "https://www.fl.ru/rss/projects.xml",
        ],
        freelancehunt_api_token="fh-token",
        freelancehunt_api_source_enabled=True,
        freelancehunt_api_pages=2,
        freelancehunt_api_skill_ids=[180, 169],
        public_project_sources=[],
        public_source_probes=[],
        send_first_run=False,
    )
    api_calls = []
    rss_calls = []
    api_post = Post(
        source="freelancehunt_api",
        post_id="freelancehunt_api:1638118",
        url="https://api.freelancehunt.com/v2/projects/1638118",
        text="Разовая задача: Telegram-бот для заявок. Бюджет: 4000 UAH.",
        published_at="2026-06-28T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: rss_calls.append(feed) or [],
        fetch_public_posts=lambda source: [],
        fetch_freelancehunt_posts=lambda token, pages, skill_ids: api_calls.append(
            (token, pages, skill_ids)
        )
        or [api_post],
        send_message=lambda text, reply_markup=None: None,
    )

    assert api_calls == [("fh-token", 2, [180, 169])]
    assert rss_calls == ["https://www.fl.ru/rss/projects.xml"]
    report = json.loads(
        (config.orders_path / "reports" / "public_sources_health.json").read_text(encoding="utf-8")
    )
    api_health = next(item for item in report["sources"] if item["source"] == "freelancehunt_api")
    assert api_health["status"] == "available"
    assert api_health["posts"] == 1


def test_run_local_agent_writes_marketplace_autopilot_plan(tmp_path):
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        auto_outreach_enabled=True,
        auto_conversation_enabled=True,
        auto_payment_watch_enabled=True,
        rss_feeds=["https://www.fl.ru/rss/projects.xml"],
        public_project_sources=["freelance_ru"],
        public_source_probes=[],
        send_first_run=False,
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=lambda source: [],
        send_message=lambda text, reply_markup=None: None,
    )

    report = json.loads(
        (config.orders_path / "reports" / "marketplace_autopilot_plan.json").read_text(encoding="utf-8")
    )
    assert report["ready_channels"] == []
    assert report["channels"][0]["key"] == "fl_ru"
    assert all(channel["key"] != "freelancehunt" for channel in report["channels"])
    assert (config.orders_path / "reports" / "marketplace_autopilot_plan.md").exists()


def test_run_local_agent_writes_email_transport_health_report(tmp_path):
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        smtp_from="robot@example.ru",
        imap_host="imap.yandex.ru",
        imap_port=993,
        public_project_sources=["freelance_ru"],
        send_first_run=False,
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=lambda source: [],
        probe_email_transport_func=lambda config: EmailTransportHealth(
            checked_at="2026-06-24T10:00:00+03:00",
            status="unavailable",
            smtp_configured=True,
            imap_configured=True,
            smtp_host="smtp.yandex.ru",
            smtp_port=465,
            imap_host="imap.yandex.ru",
            imap_port=993,
            smtp_reachable=False,
            imap_reachable=False,
            smtp_error="TimeoutError: timed out",
            imap_error="TimeoutError: timed out",
        ),
        send_message=lambda text, reply_markup=None: None,
    )

    email_report = json.loads(
        (config.orders_path / "reports" / "email_transport_health.json").read_text(encoding="utf-8")
    )
    plan = json.loads((config.orders_path / "reports" / "marketplace_autopilot_plan.json").read_text(encoding="utf-8"))
    freelance_ru = next(channel for channel in plan["channels"] if channel["key"] == "freelance_ru")
    assert email_report["status"] == "unavailable"
    assert "SMTP недоступен" in " ".join(freelance_ru["blockers"])


def test_run_local_agent_writes_execution_runtime_health_when_enabled(tmp_path, monkeypatch):
    config = replace(make_config(tmp_path), execution_verify_enabled=True)
    calls = []
    monkeypatch.setattr(
        local_agent_cli,
        "write_execution_runtime_health",
        lambda **kwargs: calls.append(kwargs),
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=None,
        send_message=lambda text, reply_markup=None: None,
    )

    assert calls == [
        {
            "path": config.orders_path / "reports" / "execution_runtime_health.json",
            "python_image": config.execution_python_image,
            "node_image": config.execution_node_image,
        }
    ]


def test_run_local_agent_continues_when_execution_runtime_health_cannot_be_written(tmp_path, monkeypatch):
    config = replace(make_config(tmp_path), execution_verify_enabled=True)
    monkeypatch.setattr(
        local_agent_cli,
        "write_execution_runtime_health",
        lambda **kwargs: (_ for _ in ()).throw(OSError(28, "No space left on device")),
    )

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=None,
        send_message=lambda text, reply_markup=None: None,
    )

    assert summary.checked == 0


def test_auto_outreach_marks_order_without_contact_unavailable(tmp_path):
    config = replace(make_config(tmp_path), auto_outreach_enabled=True, channels=[], rss_feeds=[])
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:1",
        url="https://freelance.ru/task/view/1",
        text="Нужен Telegram-бот. Бюджет 15 000 руб.",
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты"),
        status=OrderStatus.DRAFT_READY,
    )
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
    )

    assert store.load_order(order.order_id).status == OrderStatus.CONTACT_UNAVAILABLE


def test_platform_browser_without_adapter_is_terminal_and_recorded(tmp_path):
    notifications = []
    send_attempts = []
    config = replace(make_config(tmp_path), auto_outreach_enabled=True)
    store = OrderStore(config.orders_path)
    post = Post(
        source="weblancer.net",
        post_id="weblancer:1268001",
        url="https://www.weblancer.net/freelance/sozdanie-botov-61/telegram-bot-1268001/",
        text="Разовый проект: Telegram-бот для заявок.",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты"),
        status=OrderStatus.DRAFT_READY,
    )
    store.save_order(order)

    updated = local_agent_cli._maybe_auto_send_outreach(
        config=config,
        order=order,
        store=store,
        sender=lambda text, reply_markup=None: notifications.append(text),
        send_outreach=lambda order, text: send_attempts.append((order, text)),
    )

    blocked = json.loads(
        (store.order_dir(order.order_id) / "outbox" / "channel_blocked.json").read_text(encoding="utf-8")
    )
    assert updated.status == OrderStatus.CONTACT_UNAVAILABLE
    assert blocked["channel"] == "platform_browser"
    assert "адаптер" in blocked["reason"]
    assert send_attempts == []
    assert len(notifications) == 1


def test_platform_browser_dry_run_mode_does_not_mark_outreach_sent(tmp_path):
    notifications = []
    config = replace(
        make_config(tmp_path),
        auto_outreach_enabled=True,
        marketplace_browser_enabled=True,
        marketplace_browser_live_submit=False,
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="weblancer.net",
        post_id="weblancer:1268001",
        url="https://www.weblancer.net/freelance/sozdanie-botov-61/telegram-bot-1268001/",
        text="Разовый проект: Telegram-бот для заявок.",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты"),
        status=OrderStatus.DRAFT_READY,
    )
    store.save_order(order)

    updated = local_agent_cli._maybe_auto_send_outreach(
        config=config,
        order=order,
        store=store,
        sender=lambda text, reply_markup=None: notifications.append(text),
        send_outreach=lambda order, text: (_ for _ in ()).throw(AssertionError("must not send")),
    )

    assert updated.status == OrderStatus.DRAFT_READY
    assert "dry-run" in (
        store.order_dir(order.order_id) / "outbox" / "channel_blocked.json"
    ).read_text(encoding="utf-8")


def test_send_marketplace_outreach_uses_browser_adapter_for_platform_contact(tmp_path, monkeypatch):
    calls = []

    class FakeBrowserClient:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def submit(self, request, *, artifacts_dir):
            calls.append(("submit", request, artifacts_dir))
            return {"status": "submitted", "submitted": True, "reference": "response-1"}

    monkeypatch.setattr(local_agent_cli, "MarketplaceBrowserClient", FakeBrowserClient)
    config = replace(
        make_config(tmp_path),
        marketplace_browser_enabled=True,
        marketplace_browser_live_submit=True,
    )
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:4171",
        url="https://freelance.ru/task/view/4171",
        text="Нужен Python-скрипт.",
    )
    order = replace(make_order_from_post(post, category="Автоматизации и парсеры"), price_rub=12000)

    local_agent_cli._send_marketplace_outreach(config, order, "Здравствуйте! Готов выполнить задачу.")

    request = calls[1][1]
    assert request.channel == "freelance_ru"
    assert request.amount_rub == 12000
    assert calls[1][2] == config.orders_path / order.order_id / "outbox" / "browser"
    result = json.loads(
        (config.orders_path / order.order_id / "outbox" / "browser_result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "submitted"
    assert result["reference"] == "response-1"


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


class FakeQualityExecutionClient(FakeExecutionDraftClient):
    def __init__(self, *, initial_files, repaired_files=None, ai_passed=True):
        super().__init__()
        self.initial_files = initial_files
        self.repaired_files = repaired_files if repaired_files is not None else initial_files
        self.ai_passed = ai_passed
        self.review_calls = []
        self.repair_calls = []

    def draft_execution_package(self, order, conversation_text, execution_context):
        self.calls.append((order.order_id, conversation_text, execution_context))
        return ExecutionDraftPackage("Результат", self.initial_files, "Отправляю готовый результат.")

    def review_execution_package(self, order, conversation_text, package):
        self.review_calls.append(package)
        return AIQualityReview(
            passed=self.ai_passed,
            issues=() if self.ai_passed else ("Пакет не соответствует ТЗ.",),
            repair_instructions_ru="Исправь пакет по ТЗ." if not self.ai_passed else "",
        )

    def repair_execution_package(self, order, conversation_text, package, repair_instructions_ru):
        self.repair_calls.append((package, repair_instructions_ru))
        return ExecutionDraftPackage("Исправленный результат", self.repaired_files, "Отправляю исправленный результат.")


class FailingAutopilotClient:
    def analyze_order(self, order):
        raise RuntimeError("provider failed")


class TimeoutAutopilotClient:
    def __init__(self):
        self.orders = []

    def analyze_order(self, order):
        self.orders.append(order)
        raise requests.Timeout("provider timeout")


class HTTPErrorAutopilotClient:
    def __init__(self, status_code):
        self.status_code = status_code
        self.orders = []

    def analyze_order(self, order):
        self.orders.append(order)
        error = requests.HTTPError(f"{self.status_code} Client Error")
        error.response = type("Response", (), {"status_code": self.status_code})()
        raise error


def queued_config(tmp_path) -> Config:
    return replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        agent_queue_enabled=True,
        agent_queue_path=tmp_path / "orders" / "agent_jobs.sqlite3",
        agent_jobs_per_cycle=3,
        agent_job_max_attempts=4,
        agent_job_lease_seconds=600,
    )


def queue_test_post(post_id="sample/queued-1") -> Post:
    return Post(
        source="sample",
        post_id=post_id,
        url=f"https://example.com/{post_id}",
        text="Нужен Telegram-бот для заявок и Google Sheets. Оплата 12 000 руб.",
        published_at="2026-06-22T09:00:00+03:00",
    )


def test_queue_producer_does_not_call_ai_inside_monitor(tmp_path):
    config = queued_config(tmp_path)
    client = FakeAutopilotClient(safe_autopilot_result())

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [queue_test_post()],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
        process_jobs=False,
    )

    assert summary.sent == 1
    assert client.orders == []
    queue = AgentJobQueue(config.agent_queue_path)
    job = queue.enqueue(
        order_id=OrderStore(config.orders_path).list_orders()[0].order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{OrderStore(config.orders_path).list_orders()[0].order_id}",
        max_attempts=4,
        now=datetime.now(tz=UTC),
    )
    assert job.status == JobStatus.PENDING


def test_queue_worker_advances_order_once(tmp_path):
    config = queued_config(tmp_path)
    client = FakeAutopilotClient(safe_autopilot_result())

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [queue_test_post()],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )
    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )

    assert len(client.orders) == 1
    queue = AgentJobQueue(config.agent_queue_path)
    assert queue.counts() == {"succeeded": 1}


def test_queue_worker_retries_timeout_without_telegram_spam(tmp_path):
    config = queued_config(tmp_path)
    client = TimeoutAutopilotClient()
    sent = []

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [queue_test_post()],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append(text),
        autopilot_client=client,
    )

    queue = AgentJobQueue(config.agent_queue_path)
    assert queue.counts() == {"pending": 1}
    assert len(client.orders) == 1
    assert not any("AI-черновик" in text for text in sent)


def test_queue_worker_dead_letters_terminal_http_error_once(tmp_path):
    config = queued_config(tmp_path)
    client = HTTPErrorAutopilotClient(422)
    sent = []

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [queue_test_post()],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append(text),
        autopilot_client=client,
    )

    queue = AgentJobQueue(config.agent_queue_path)
    assert queue.counts() == {"dead": 1}
    order = OrderStore(config.orders_path).list_orders()[0]
    assert (config.orders_path / order.order_id / "jobs" / "dead.json").exists()
    assert sum("окончательно остановлена" in text for text in sent) == 1


def test_queue_worker_dead_letters_exhausted_retry(tmp_path):
    config = replace(queued_config(tmp_path), agent_job_max_attempts=1)
    client = TimeoutAutopilotClient()

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [queue_test_post()],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )

    assert AgentJobQueue(config.agent_queue_path).counts() == {"dead": 1}


def test_queue_worker_completes_job_for_already_advanced_order(tmp_path):
    config = queued_config(tmp_path)
    store = OrderStore(config.orders_path)
    order = replace(
        make_order_from_post(queue_test_post(), category="Telegram-боты"),
        status=OrderStatus.SKIPPED,
    )
    store.save_order(order)
    queue = AgentJobQueue(config.agent_queue_path)
    queue.enqueue(
        order_id=order.order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{order.order_id}",
        max_attempts=4,
        now=datetime.now(tz=UTC),
    )
    client = FakeAutopilotClient(safe_autopilot_result())

    _process_agent_jobs(
        config=config,
        store=store,
        queue=queue,
        sender=lambda text, reply_markup=None: None,
        autopilot_client=client,
        send_outreach=None,
        recovered_leases=0,
    )

    assert client.orders == []
    assert queue.counts() == {"succeeded": 1}


def test_queue_reopens_dead_pending_order_after_restart(tmp_path):
    config = queued_config(tmp_path)
    store = OrderStore(config.orders_path)
    order = make_order_from_post(queue_test_post(), category="Telegram-боты")
    store.save_order(order)
    queue = AgentJobQueue(config.agent_queue_path)
    job = queue.enqueue(
        order_id=order.order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{order.order_id}",
        max_attempts=4,
        now=datetime.now(tz=UTC),
    )
    claimed = queue.claim_next(lease_seconds=600, now=datetime.now(tz=UTC))
    assert claimed is not None
    queue.fail(claimed.job_id, ValueError("old parser error"), now=datetime.now(tz=UTC))
    client = FakeAutopilotClient(safe_autopilot_result())

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )

    assert AgentJobQueue(config.agent_queue_path).get(job.job_id).status == JobStatus.SUCCEEDED
    assert store.load_order(order.order_id).status == OrderStatus.DRAFT_READY


def test_queue_skips_stale_pending_order_before_ai_call(tmp_path):
    config = replace(queued_config(tmp_path), auto_outreach_max_age_hours=24)
    store = OrderStore(config.orders_path)
    order = replace(
        make_order_from_post(queue_test_post(), category="Telegram-боты"),
        created_at="01.01.2020 00:00 МСК",
        updated_at="01.01.2020 00:00 МСК",
    )
    store.save_order(order)
    queue = AgentJobQueue(config.agent_queue_path)
    queue.enqueue(
        order_id=order.order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{order.order_id}",
        max_attempts=4,
        now=datetime.now(tz=UTC),
    )
    client = FakeAutopilotClient(safe_autopilot_result())

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )

    assert client.orders == []
    assert store.load_order(order.order_id).status == OrderStatus.SKIPPED
    assert AgentJobQueue(config.agent_queue_path).counts() == {"succeeded": 1}


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


class FakeEmailInboundClient:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.marked_seen = []

    def list_unseen_messages(self):
        return self.messages

    def mark_seen(self, message_id):
        self.marked_seen.append(message_id)


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
        freelancehunt_bid_api_enabled=True,
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


def test_run_local_agent_retries_email_outreach_after_smtp_transport_recovers(tmp_path):
    sent = []
    send_attempts = []
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        auto_outreach_enabled=True,
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        smtp_from="robot@example.ru",
        public_project_sources=["freelance_ru"],
        channels=[],
        rss_feeds=[],
    )
    post = Post(
        source="freelance_ru",
        post_id="freelance_ru:blocked-email",
        url="https://freelance.ru/task/view/blocked-email",
        text="Нужен Telegram-бот для заявок. Почта client@example.ru. Бюджет 12 000 руб.",
        published_at="2026-06-24T12:00:00+03:00",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=lambda source: [post],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
        send_outreach=lambda order, text: send_attempts.append((order.order_id, text)),
        probe_email_transport_func=lambda config: EmailTransportHealth(
            checked_at="2026-06-24T12:00:00+03:00",
            status="unavailable",
            smtp_configured=True,
            imap_configured=False,
            smtp_host="smtp.yandex.ru",
            smtp_port=465,
            smtp_reachable=False,
            imap_reachable=False,
            smtp_error="TimeoutError: timed out",
        ),
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.DRAFT_READY
    assert send_attempts == []
    assert any("SMTP недоступен" in message for message, _ in sent)
    blocked_report = store.order_dir(order.order_id) / "outbox" / "channel_blocked.json"
    assert "SMTP недоступен" in blocked_report.read_text(encoding="utf-8")

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=lambda source: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
        send_outreach=lambda order, text: send_attempts.append((order.order_id, text)),
        probe_email_transport_func=lambda config: EmailTransportHealth(
            checked_at="2026-06-24T12:05:00+03:00",
            status="degraded",
            smtp_configured=True,
            imap_configured=False,
            smtp_host="smtp.yandex.ru",
            smtp_port=465,
            smtp_reachable=True,
            imap_reachable=False,
        ),
    )

    assert store.load_order(order_id).status == OrderStatus.OUTREACH_SENT
    assert send_attempts == [(order_id, "Здравствуйте! Готов выполнить Telegram-бота для заявок.")]
    assert not blocked_report.exists()


def test_run_local_agent_writes_send_failure_diagnostics_for_failed_outreach(tmp_path):
    sent = []
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        freelancehunt_bid_api_enabled=True,
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

    def failing_send_outreach(order, text):
        error = requests.HTTPError("422 Client Error")
        error.response = type(
            "Response",
            (),
            {
                "status_code": 422,
                "json": lambda self: {
                    "error": {
                        "status": 422,
                        "title": "Unprocessable Entity",
                        "detail": "Profile verification required",
                        "meta": {"info": {"profile": ["Verify phone"]}},
                    }
                },
            },
        )()
        raise error

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
        send_outreach=failing_send_outreach,
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.SEND_FAILED

    payload = json.loads(
        (store.order_dir(order.order_id) / "outbox" / "send_failure.json").read_text(encoding="utf-8")
    )
    assert payload["error"] == "HTTPError"
    assert payload["status_code"] == 422
    assert payload["endpoint"] == "/projects/123456/bids"
    assert payload["api_error"] == {
        "status": 422,
        "title": "Unprocessable Entity",
        "detail": "Profile verification required",
        "meta": {"info": {"profile": ["Verify phone"]}},
    }
    assert any("не отправлен: HTTPError" in message for message, _ in sent)


def test_run_local_agent_closes_order_when_freelancehunt_project_is_gone(tmp_path):
    sent = []
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        freelancehunt_bid_api_enabled=True,
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

    def gone_send_outreach(order, text):
        error = requests.HTTPError("410 Client Error")
        error.response = type("Response", (), {"status_code": 410})()
        raise error

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [post],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        autopilot_client=FakeAutopilotClient(safe_autopilot_result()),
        send_outreach=gone_send_outreach,
    )

    store = OrderStore(config.orders_path)
    order_id = next(Path(config.orders_path).glob("*/state.json")).parent.name
    order = store.load_order(order_id)
    assert order.status == OrderStatus.CLOSED
    payload = json.loads(
        (store.order_dir(order.order_id) / "outbox" / "send_failure.json").read_text(encoding="utf-8")
    )
    assert payload["status_code"] == 410


def test_run_local_agent_retries_retryable_send_failed_outreach(tmp_path):
    auto_sent = []
    config = replace(
        make_config(tmp_path),
        auto_outreach_enabled=True,
        auto_outreach_max_age_hours=0,
        freelancehunt_api_token="fh-token",
        freelancehunt_bid_api_enabled=True,
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок. Бюджет 12 000 руб.",
        published_at="2026-06-25T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты"),
        status=OrderStatus.SEND_FAILED,
        price_rub=12000,
    )
    store.save_order(order)
    order_dir = store.order_dir(order.order_id)
    (order_dir / "autopilot").mkdir(parents=True, exist_ok=True)
    (order_dir / "autopilot" / "outreach.md").write_text("Здравствуйте! Готов выполнить задачу.", encoding="utf-8")
    (order_dir / "outbox").mkdir(parents=True, exist_ok=True)
    (order_dir / "outbox" / "send_failure.json").write_text(
        json.dumps({"status_code": 500}, ensure_ascii=False),
        encoding="utf-8",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=None,
        send_message=lambda text, reply_markup=None: None,
        send_outreach=lambda order, text: auto_sent.append((order.order_id, text)),
    )

    assert store.load_order(order.order_id).status == OrderStatus.OUTREACH_SENT
    assert auto_sent == [(order.order_id, "Здравствуйте! Готов выполнить задачу.")]


def test_run_local_agent_closes_existing_send_failed_gone_order(tmp_path):
    auto_sent = []
    sent = []
    config = replace(
        make_config(tmp_path),
        auto_outreach_enabled=True,
        freelancehunt_api_token="fh-token",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок. Бюджет 12 000 руб.",
        published_at="2026-06-25T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты"), status=OrderStatus.SEND_FAILED)
    store.save_order(order)
    order_dir = store.order_dir(order.order_id)
    (order_dir / "outbox").mkdir(parents=True, exist_ok=True)
    (order_dir / "outbox" / "send_failure.json").write_text(
        json.dumps({"status_code": 410}, ensure_ascii=False),
        encoding="utf-8",
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        fetch_public_posts=None,
        send_message=lambda text, reply_markup=None: sent.append(text),
        send_outreach=lambda order, text: auto_sent.append((order.order_id, text)),
    )

    assert store.load_order(order.order_id).status == OrderStatus.CLOSED
    assert auto_sent == []
    assert any("закрыт" in message.lower() and "410" in message for message in sent)


def test_run_local_agent_auto_sends_when_ai_warnings_are_non_blocking(tmp_path):
    auto_sent = []
    result = replace(safe_autopilot_result(), risk_flags=["уточнить формат доступа к Google Sheets"])
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        freelancehunt_bid_api_enabled=True,
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


def test_run_local_agent_auto_sends_safe_email_reply(tmp_path):
    sent = []
    auto_sent = []
    email_client = FakeEmailInboundClient(
        [
            EmailInboundMessage(
                message_id="msg-1@example.ru",
                from_email="client@example.ru",
                subject="Re: Project",
                text="Здравствуйте, можете начать сегодня?",
                created_at="23.06.2026 10:30 МСК",
                raw={"uid": "101"},
            )
        ]
    )
    reply_client = FakeConversationReplyClient("Здравствуйте! Да, могу начать сегодня после уточнения доступа к таблице.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_reply_enabled=True,
        openai_api_key="sk-test",
        imap_host="imap.example.ru",
        smtp_host="smtp.example.ru",
        smtp_from="robot@example.ru",
        channels=[],
        rss_feeds=[],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:3272",
        url="https://freelance.ru/task/view/3272",
        text="Нужен Telegram-бот для заявок. client@example.ru",
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        email_inbound_client=email_client,
        conversation_reply_client=reply_client,
        send_outreach=lambda order, text: auto_sent.append((order.contact.value, text)),
    )

    assert email_client.marked_seen == ["msg-1@example.ru"]
    assert auto_sent == [
        ("client@example.ru", "Здравствуйте! Да, могу начать сегодня после уточнения доступа к таблице.")
    ]
    order_dir = store.order_dir(order.order_id)
    assert (order_dir / "outbox" / "email_reply_client_example_ru.sent.json").exists()
    assert "можете начать сегодня" in (order_dir / "conversation.md").read_text(encoding="utf-8")
    assert store.load_order(order.order_id).status == OrderStatus.DISCOVERY
    assert any("AI-ответ отправлен заказчику по email" in message for message, _ in sent)


def test_run_local_agent_skips_email_sync_when_imap_transport_is_unreachable(tmp_path):
    sent = []
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        imap_host="imap.yandex.ru",
        imap_port=993,
        channels=[],
        rss_feeds=[],
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        probe_email_transport_func=lambda config: EmailTransportHealth(
            checked_at="2026-06-25T10:00:00+03:00",
            status="unavailable",
            smtp_configured=False,
            imap_configured=True,
            imap_host="imap.yandex.ru",
            imap_port=993,
            smtp_reachable=False,
            imap_reachable=False,
            imap_error="TimeoutError: timed out",
        ),
    )

    assert not any("Синхронизация email-переписки не выполнена" in message for message, _ in sent)
    report = config.orders_path / "reports" / "email_sync_skipped.json"
    assert "IMAP недоступен: TimeoutError: timed out" in report.read_text(encoding="utf-8")


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
    execution_client = FakeQualityExecutionClient(
        initial_files={
            "bot.py": "print('ready')\n",
            "README.md": "# Запуск\n\n`python bot.py`\n",
            ".env.example": "TELEGRAM_BOT_TOKEN=\n",
        }
    )
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_reply_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        auto_delivery_enabled=True,
        auto_quality_enabled=True,
        delivery_public_base_url="https://files.example.ru/freelance",
        delivery_public_dir=tmp_path / "public",
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
    assert conversation_client.thread_messages
    thread_id, sent_text = conversation_client.thread_messages[-1]
    assert thread_id == "thread-1"
    assert "Отправляю готовый результат." in sent_text
    assert "Пакет результата" in sent_text
    assert f"https://files.example.ru/freelance/{order.order_id}/delivery_package.zip" in sent_text
    assert (store.order_dir(order.order_id) / "outbox" / "delivery_message.sent.json").exists()
    receipt = json.loads((store.order_dir(order.order_id) / "outbox" / "delivery_receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "sent"
    assert receipt["channel"] == "freelancehunt"
    assert receipt["delivery_mode"] == "thread_message"
    assert receipt["attachment_supported"] is False
    assert receipt["archive"] == "outbox/delivery_package.zip"
    assert receipt["public_url"] == f"https://files.example.ru/freelance/{order.order_id}/delivery_package.zip"
    assert receipt["public_path"] == f"{order.order_id}/delivery_package.zip"
    assert receipt["quality"]["passed"] is True
    assert "execution/generated/bot.py" in receipt["generated_files"]
    assert (tmp_path / "public" / order.order_id / "delivery_package.zip").exists()
    assert not (store.order_dir(order.order_id) / "outbox" / "delivery_approval_requested.json").exists()
    assert any("Результат автоматически отправлен заказчику" in message for message, _ in sent)


def test_auto_delivery_appends_static_payment_request_for_email_order(tmp_path):
    sent = []
    delivered = []
    config = replace(
        make_config(tmp_path),
        auto_delivery_enabled=True,
        payment_instructions_ru="Оплата переводом на карту РФ после проверки результата.",
    )
    store = OrderStore(config.orders_path)
    order = _email_delivery_order(store)

    local_agent_cli._maybe_finalize_delivery(
        store=store,
        order=order,
        sender=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        config=config,
        send_delivery=lambda order, text: delivered.append((order.order_id, text)),
        quality_client=None,
    )

    updated = store.load_order(order.order_id)
    payment_path = store.order_dir(order.order_id) / "payment" / "request.json"
    assert updated.status == OrderStatus.PAYMENT_REQUESTED
    assert payment_path.exists()
    assert delivered
    assert "Платежный канал" in delivered[0][1]
    assert "Оплата переводом на карту РФ" in delivered[0][1]
    assert "Пакет результата" in delivered[0][1]
    assert "Результат автоматически отправлен заказчику" in sent[-1][0]


def test_marketplace_email_delivery_attaches_package_archive(tmp_path, monkeypatch):
    sent = []
    config = replace(
        make_config(tmp_path),
        smtp_host="smtp.example.ru",
        smtp_port=465,
        smtp_username="robot@example.ru",
        smtp_password="secret",
        smtp_from="robot@example.ru",
        smtp_use_ssl=True,
    )
    store = OrderStore(config.orders_path)
    order = _email_delivery_order(store)
    archive_path = store.order_dir(order.order_id) / "outbox" / "delivery_package.zip"
    archive_path.write_bytes(b"zip-content")

    class FakeSMTPOutreachClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def send(self, order, text, *, attachments=None):
            sent.append((order.order_id, text, attachments))

    monkeypatch.setattr(local_agent_cli, "SMTPOutreachClient", FakeSMTPOutreachClient)

    local_agent_cli._send_marketplace_delivery(config, order, "Результат готов.")

    assert sent == [(order.order_id, "Результат готов.", [archive_path])]


def test_marketplace_email_followup_does_not_attach_delivery_archive(tmp_path, monkeypatch):
    sent = []
    config = replace(
        make_config(tmp_path),
        smtp_host="smtp.example.ru",
        smtp_port=465,
        smtp_username="robot@example.ru",
        smtp_password="secret",
        smtp_from="robot@example.ru",
        smtp_use_ssl=True,
    )
    store = OrderStore(config.orders_path)
    order = _email_delivery_order(store)
    archive_path = store.order_dir(order.order_id) / "outbox" / "delivery_package.zip"
    archive_path.write_bytes(b"zip-content")

    class FakeSMTPOutreachClient:
        def __init__(self, **kwargs):
            pass

        def send(self, order, text, *, attachments=None):
            sent.append((order.order_id, text, attachments))

    monkeypatch.setattr(local_agent_cli, "SMTPOutreachClient", FakeSMTPOutreachClient)

    local_agent_cli._send_marketplace_followup(config, order, "Напоминание об оплате.")

    assert sent == [(order.order_id, "Напоминание об оплате.", None)]


def test_marketplace_outreach_blocks_bid_when_preflight_project_is_not_open(tmp_path, monkeypatch):
    config = replace(make_config(tmp_path), freelancehunt_api_token="fh-token")
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/bot/123456.html",
        url="https://freelancehunt.com/project/bot/123456.html",
        text="Нужен Telegram-бот, бюджет 15 000 руб.",
        published_at="2026-06-28T10:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), price_rub=15000)
    store.save_order(order)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get_profile(self):
            return {
                "data": {
                    "id": 1965999,
                    "type": "freelancer",
                    "attributes": {"verification": {"identity": False, "birth_date": False, "phone": False, "email": True}},
                }
            }

        def get_project(self, project_id):
            return {
                "data": {
                    "id": project_id,
                    "type": "project",
                    "attributes": {
                        "status": {"id": 13, "name": "Contractor chosen"},
                        "safe_type": "employer",
                        "freelancer": {"id": 99},
                    },
                }
            }

        def add_bid(self, **kwargs):
            raise AssertionError("bid must not be sent")

    monkeypatch.setattr(local_agent_cli, "FreelancehuntClient", FakeClient)

    try:
        local_agent_cli._send_marketplace_outreach(config, order, "Готов выполнить задачу.")
    except RuntimeError as exc:
        assert type(exc).__name__ == "FreelancehuntBidPreflightError"
    else:
        raise AssertionError("closed project must fail preflight")

    report = json.loads(
        (store.order_dir(order.order_id) / "outbox" / "freelancehunt_preflight.json").read_text(encoding="utf-8")
    )
    assert report["eligible"] is False
    assert report["project"]["status_id"] == 13
    assert report["blockers"] == ["project_not_open_for_proposals", "project_has_contractor"]


def test_marketplace_outreach_sends_bid_after_open_project_preflight(tmp_path, monkeypatch):
    bids = []
    config = replace(make_config(tmp_path), freelancehunt_api_token="fh-token")
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/bot/123456.html",
        url="https://freelancehunt.com/project/bot/123456.html",
        text="Нужен Telegram-бот, бюджет 15 000 руб.",
        published_at="2026-06-28T10:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), price_rub=15000)
    store.save_order(order)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get_profile(self):
            return {
                "data": {
                    "id": 1965999,
                    "type": "freelancer",
                    "attributes": {"verification": {"identity": False, "birth_date": False, "phone": False, "email": True}},
                }
            }

        def get_project(self, project_id):
            return {
                "data": {
                    "id": project_id,
                    "type": "project",
                    "attributes": {
                        "status": {"id": 11, "name": "Open for proposals"},
                        "safe_type": "employer",
                        "budget": {"amount": 4000, "currency": "UAH"},
                        "freelancer": None,
                    },
                }
            }

        def add_bid(self, *, project_id, bid):
            bids.append((project_id, bid))
            return {"data": {"id": 1}}

    monkeypatch.setattr(local_agent_cli, "FreelancehuntClient", FakeClient)

    local_agent_cli._send_marketplace_outreach(config, order, "Готов выполнить задачу.")

    assert len(bids) == 1
    assert bids[0][1].amount == 4000
    assert bids[0][1].currency == "UAH"
    report = json.loads(
        (store.order_dir(order.order_id) / "outbox" / "freelancehunt_preflight.json").read_text(encoding="utf-8")
    )
    assert report["eligible"] is True
    assert report["warnings"] == [
        "profile_identity_not_verified",
        "profile_birth_date_not_verified",
        "profile_phone_not_verified",
    ]


def test_open_project_bid_410_is_kept_for_profile_diagnostics(tmp_path, monkeypatch):
    config = replace(make_config(tmp_path), freelancehunt_api_token="fh-token")
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/bot/123456.html",
        url="https://freelancehunt.com/project/bot/123456.html",
        text="Нужен Telegram-бот, бюджет 15 000 руб.",
        published_at="2026-06-28T10:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), price_rub=15000)
    store.save_order(order)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get_profile(self):
            return {
                "data": {
                    "id": 1965999,
                    "type": "freelancer",
                    "attributes": {"verification": {"identity": False, "birth_date": False, "phone": False, "email": True}},
                }
            }

        def get_project(self, project_id):
            return {
                "data": {
                    "id": project_id,
                    "type": "project",
                    "attributes": {
                        "status": {"id": 11, "name": "Open for proposals"},
                        "safe_type": "employer",
                        "freelancer": None,
                    },
                }
            }

        def add_bid(self, **kwargs):
            error = requests.HTTPError("410 Client Error")
            error.response = type("Response", (), {"status_code": 410})()
            raise error

    monkeypatch.setattr(local_agent_cli, "FreelancehuntClient", FakeClient)

    try:
        local_agent_cli._send_marketplace_outreach(config, order, "Готов выполнить задачу.")
    except requests.HTTPError as exc:
        assert local_agent_cli._outreach_failure_status(exc) == OrderStatus.SEND_FAILED
        assert exc.freelancehunt_preflight["eligible"] is True
    else:
        raise AssertionError("bid error must propagate")


def test_deprecated_freelancehunt_bid_endpoint_marks_contact_unavailable():
    error = requests.HTTPError("410 Client Error")
    error.response = type(
        "Response",
        (),
        {
            "status_code": 410,
            "json": lambda self: {
                "error": {
                    "status": 410,
                    "title": "This public endpoint is no longer available due to API v2 deprecation.",
                }
            },
        },
    )()

    assert local_agent_cli._outreach_failure_status(error) == OrderStatus.CONTACT_UNAVAILABLE


def test_recovery_keeps_open_project_when_bid_endpoint_is_deprecated(tmp_path):
    sent = []
    config = replace(make_config(tmp_path), auto_outreach_enabled=True)
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt_api",
        post_id="freelancehunt_api:1638234",
        url="https://freelancehunt.com/project/bot/1638234.html",
        text="Нужен Telegram-бот, бюджет обсуждается.",
        published_at="2026-06-29T10:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.SEND_FAILED,
    )
    store.save_order(order)
    outbox = store.order_dir(order.order_id) / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "send_failure.json").write_text(
        json.dumps(
            {
                "status_code": 410,
                "api_error": {
                    "status": 410,
                    "title": "This public endpoint is no longer available due to API v2 deprecation.",
                },
            }
        ),
        encoding="utf-8",
    )

    updated = local_agent_cli._recover_send_failed_outreach(
        config=config,
        order=order,
        store=store,
        sender=lambda text, reply_markup=None: sent.append(text),
        send_outreach=lambda order, text: None,
    )

    assert updated.status == OrderStatus.CONTACT_UNAVAILABLE
    assert any("API откликов отключен" in message for message in sent)


def test_auto_delivery_blocks_email_order_without_payment_channel(tmp_path):
    sent = []
    delivered = []
    config = replace(make_config(tmp_path), auto_delivery_enabled=True)
    store = OrderStore(config.orders_path)
    order = _email_delivery_order(store)

    local_agent_cli._maybe_finalize_delivery(
        store=store,
        order=order,
        sender=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        config=config,
        send_delivery=lambda order, text: delivered.append((order.order_id, text)),
        quality_client=None,
    )

    assert delivered == []
    assert "нет платежного канала для email-заказа" in sent[0][0]
    assert store.load_order(order.order_id).status == OrderStatus.AWAITING_DELIVERY_APPROVAL


def _email_delivery_order(store: OrderStore):
    post = Post(
        source="freelance_ru",
        post_id="freelance_ru/email-order",
        url="https://www.freelance.ru/projects/email-order",
        text="Нужен парсер сайта, бюджет 12 000 руб. Почта client@example.ru",
        published_at="2026-06-23T10:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Автоматизации/парсеры", risks=[]),
        status=OrderStatus.OUTREACH_SENT,
        contact=CustomerContact(channel="email", value="client@example.ru", can_auto_send=True),
    )
    store.save_order(order)
    order_dir = store.order_dir(order.order_id)
    (order_dir / "execution" / "generated").mkdir(parents=True)
    (order_dir / "execution" / "generated" / "parser.py").write_text("print('ready')\n", encoding="utf-8")
    (order_dir / "outbox").mkdir(parents=True)
    (order_dir / "outbox" / "delivery_message.md").write_text(
        "Здравствуйте! Подготовил результат для проверки.\n",
        encoding="utf-8",
    )
    return order


def test_quality_gate_sends_package_that_passes_local_and_ai_checks(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(
        initial_files={
            "bot.py": "print('ready')\n",
            "README.md": "# Запуск\n\n`python bot.py`\n",
            ".env.example": "TELEGRAM_BOT_TOKEN=\n",
        }
    )
    config, store, order = _quality_delivery_setup(tmp_path)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED
    assert len(execution_client.review_calls) == 1
    assert execution_client.repair_calls == []
    assert (store.order_dir(order.order_id) / "quality" / "latest.json").exists()
    assert conversation_client.thread_messages
    assert conversation_client.thread_messages[-1][0] == "thread-1"
    assert "Отправляю готовый результат." in conversation_client.thread_messages[-1][1]
    assert "Пакет результата" in conversation_client.thread_messages[-1][1]


def _verification_report(status, issues=()):
    return ExecutionVerificationReport(
        status=status,
        project_type=ProjectType.PYTHON,
        commands=(CommandResult("python_ast", 0, "ok", ""),),
        issues=tuple(issues),
        started_at="2026-06-22T20:00:00+00:00",
        finished_at="2026-06-22T20:00:01+00:00",
        duration_seconds=1.0,
        runtime={"name": "docker", "image": "runner:test"},
    )


def test_quality_gate_requires_passed_container_verification(tmp_path, monkeypatch):
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(
        initial_files={"bot.py": "print('ready')\n", "README.md": "# Запуск\n"}
    )
    config, store, order = _quality_delivery_setup(tmp_path)
    config = replace(config, execution_verify_enabled=True)
    monkeypatch.setattr(
        "vacancy_monitor.local_agent_cli.DockerExecutionVerifier",
        lambda **kwargs: type("Verifier", (), {"verify": lambda self, path: _verification_report(VerificationStatus.PASSED)})(),
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    latest = json.loads((store.order_dir(order.order_id) / "quality" / "latest.json").read_text())
    assert latest["execution_verification"]["status"] == "passed"
    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED


def test_quality_gate_blocks_runtime_unavailable_without_repair(tmp_path, monkeypatch):
    execution_client = FakeQualityExecutionClient(
        initial_files={"bot.py": "print('ready')\n", "README.md": "# Запуск\n"}
    )
    config, store, order = _quality_delivery_setup(tmp_path)
    config = replace(config, execution_verify_enabled=True)
    report = _verification_report(
        VerificationStatus.RUNTIME_UNAVAILABLE,
        (VerificationIssue("runtime_unavailable", "Docker недоступен."),),
    )
    monkeypatch.setattr(
        "vacancy_monitor.local_agent_cli.DockerExecutionVerifier",
        lambda **kwargs: type("Verifier", (), {"verify": lambda self, path: report})(),
    )

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=FakeFreelancehuntConversationClient(),
        execution_draft_client=execution_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.QUALITY_FAILED
    assert execution_client.repair_calls == []


def test_quality_gate_repairs_local_failure_then_sends(tmp_path):
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(
        initial_files={"bot.py": "print('draft')\n"},
        repaired_files={"bot.py": "print('ready')\n", "README.md": "# Запуск\n\n`python bot.py`\n"},
    )
    config, store, order = _quality_delivery_setup(tmp_path)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED
    assert len(execution_client.repair_calls) == 1
    generated = store.order_dir(order.order_id) / "execution" / "generated"
    assert (generated / "README.md").exists()
    assert conversation_client.thread_messages
    assert conversation_client.thread_messages[-1][0] == "thread-1"
    assert "Отправляю исправленный результат." in conversation_client.thread_messages[-1][1]
    assert "Пакет результата" in conversation_client.thread_messages[-1][1]


def test_quality_gate_repairs_spreadsheet_package_without_structured_file(tmp_path):
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(
        initial_files={"README.md": "# Дашборд\n\nПодготовлено описание результата.\n"},
        repaired_files={"report.csv": "metric,value\nleads,12\nsales,3\n"},
    )
    config, store, order = _quality_delivery_setup(tmp_path)
    order = replace(order, category="Таблицы и дашборды")
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    latest = json.loads((store.order_dir(order.order_id) / "quality" / "attempt-001.json").read_text(encoding="utf-8"))
    assert any(issue["code"] == "spreadsheet_deliverable_missing" for issue in latest["local"]["issues"])
    assert len(execution_client.repair_calls) == 1
    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED
    assert conversation_client.thread_messages
    assert conversation_client.thread_messages[-1][0] == "thread-1"
    assert "Отправляю исправленный результат." in conversation_client.thread_messages[-1][1]
    assert "Пакет результата" in conversation_client.thread_messages[-1][1]


def test_quality_gate_uses_task_route_for_dashboard_requirements(tmp_path):
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(
        initial_files={"README.md": "# Дашборд\n\nПодготовлено описание результата.\n"},
        repaired_files={"dashboard.csv": "metric,value\nrevenue,120000\n"},
    )
    config, store, order = _quality_delivery_setup(tmp_path)
    order = replace(order, category="Дашборды", original_text="Нужен dashboard по продажам без упоминания таблиц.")
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    latest = json.loads((store.order_dir(order.order_id) / "quality" / "attempt-001.json").read_text(encoding="utf-8"))
    route = json.loads((store.order_dir(order.order_id) / "execution" / "task_route.json").read_text(encoding="utf-8"))
    assert route["task_type"] == "dashboard"
    assert any(issue["code"] == "spreadsheet_deliverable_missing" for issue in latest["local"]["issues"])
    assert store.load_order(order.order_id).status == OrderStatus.PAYMENT_REQUESTED


def test_quality_gate_fails_after_two_repairs_without_manual_approval(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient()
    execution_client = FakeQualityExecutionClient(initial_files={"bot.py": "print('still incomplete')\n"})
    config, store, order = _quality_delivery_setup(tmp_path)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    order_dir = store.order_dir(order.order_id)
    assert store.load_order(order.order_id).status == OrderStatus.QUALITY_FAILED
    assert len(execution_client.repair_calls) == 2
    assert conversation_client.thread_messages == []
    assert not (order_dir / "outbox" / "delivery_approval_requested.json").exists()
    assert (order_dir / "quality" / "quality_failed.json").exists()
    assert len(list((order_dir / "quality").glob("attempt-*.json"))) == 3
    assert any("quality_failed" in message for message, _ in sent)


def _quality_delivery_setup(tmp_path):
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        auto_conversation_enabled=True,
        auto_execution_enabled=True,
        auto_execution_draft_enabled=True,
        auto_delivery_enabled=True,
        auto_quality_enabled=True,
        auto_quality_max_repairs=2,
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
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)
    return config, store, order


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
    ledger = load_payment_ledger(store=store, order=order)
    assert ledger["current_status"] == "confirmed"
    assert ledger["confirmed_amount_rub"] == 15000
    assert ledger["events"][-1]["event"] == "payment_confirmed"
    assert ledger["events"][-1]["provider"] == "freelancehunt_safe"
    assert any("Проект завершен на Freelancehunt" in message for message, _ in sent)


def test_run_local_agent_sends_due_payment_reminder_only_once(tmp_path):
    sent = []
    reminders = []
    config = replace(
        make_config(tmp_path),
        auto_payment_reminder_enabled=True,
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
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.PAYMENT_REQUESTED,
        updated_at="25.06.2026 10:00 МСК",
        price_rub=15000,
    )
    store.save_order(order)
    payment_dir = store.order_dir(order.order_id) / "payment"
    payment_dir.mkdir(parents=True)
    (payment_dir / "ledger.json").write_text(
        json.dumps(
            {
                "order_id": order.order_id,
                "current_status": "requested",
                "requested_amount_rub": 15000,
                "confirmed_amount_rub": 0,
                "events": [
                    {
                        "event": "payment_requested",
                        "status": "requested",
                        "created_at": "25.06.2026 10:00 МСК",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for _ in range(2):
        run_local_agent_once(
            config,
            fetch_posts=lambda channel: [],
            fetch_rss_posts=lambda feed: [],
            send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
            send_payment_reminder=lambda order, text: reminders.append((order.order_id, text)),
        )

    assert len(reminders) == 1
    assert reminders[0][0] == order.order_id
    assert "15 000 ₽" in reminders[0][1]
    history = load_payment_reminders(store=store, order=order)
    assert [(item["sequence"], item["status"]) for item in history["events"]] == [(1, "sent")]
    assert any("Напоминание об оплате отправлено" in message for message, _ in sent)


def test_run_local_agent_records_customer_payment_signal_without_closing_order(tmp_path):
    sent = []
    conversation_client = FakeFreelancehuntConversationClient(
        unread=True,
        messages=[
            FreelancehuntThreadMessage(
                message_id="msg-paid",
                text="Оплатил по СБП, проверьте поступление.",
                created_at="2026-06-26T10:00:00+03:00",
                author_id="client-1",
                author_type="employer",
                is_own=False,
                raw={"id": "msg-paid"},
            )
        ],
    )
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
    order = replace(
        make_order_from_post(post, category="Telegram-боты", risks=[]),
        status=OrderStatus.PAYMENT_REQUESTED,
        price_rub=15000,
    )
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
        freelancehunt_client=conversation_client,
    )

    updated = store.load_order(order.order_id)
    assert updated.status == OrderStatus.PAYMENT_REQUESTED
    ledger = load_payment_ledger(store=store, order=updated)
    assert ledger["current_status"] == "awaiting_confirmation"
    assert ledger["events"][-1]["event"] == "payment_signal_received"
    assert ledger["events"][-1]["amount_rub"] == 15000
    assert any("Заказчик сообщил об оплате" in message for message, _ in sent)


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
    revision_summary = json.loads(
        (store.order_dir(order.order_id) / "revisions" / "summary.json").read_text(encoding="utf-8")
    )
    assert revision_summary["sent_count"] == 1
    assert revision_summary["blocked_count"] == 0
    assert revision_summary["latest_status"] == "sent"
    assert any("Правки автоматически внесены" in message for message, _ in sent)


def test_revision_is_not_sent_when_quality_gate_exhausts_repairs(tmp_path):
    revision_message = FreelancehuntThreadMessage(
        message_id="msg-revision-quality",
        text="Нужно исправить ошибку и отправить обновленную версию.",
        created_at="2026-06-20T10:00:00+03:00",
        author_id="client-1",
        author_type="employer",
        is_own=False,
        raw={"id": "msg-revision-quality"},
    )
    conversation_client = FakeFreelancehuntConversationClient(messages=[revision_message])
    execution_client = FakeQualityExecutionClient(initial_files={"bot.py": "print('incomplete')\n"})
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        auto_conversation_enabled=True,
        auto_revision_enabled=True,
        auto_delivery_enabled=True,
        auto_quality_enabled=True,
        auto_quality_max_repairs=2,
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
        published_at="2026-06-20T09:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.PAYMENT_REQUESTED)
    store.save_order(order)

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        freelancehunt_client=conversation_client,
        execution_draft_client=execution_client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.QUALITY_FAILED
    assert len(execution_client.repair_calls) == 2
    assert conversation_client.thread_messages == []
    assert not list((store.order_dir(order.order_id) / "revisions").glob("*/delivery_message.sent.json"))


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
    revision_summary = json.loads(
        (store.order_dir(order.order_id) / "revisions" / "summary.json").read_text(encoding="utf-8")
    )
    assert revision_summary["sent_count"] == 0
    assert revision_summary["blocked_count"] == 1
    assert revision_summary["latest_status"] == "blocked"
    assert "опасный маркер" in revision_summary["latest_reason"]
    assert any("Автоправка заблокирована" in message for message, _ in sent)


def test_run_local_agent_blocks_revision_when_per_order_limit_exhausted(tmp_path):
    sent = []
    revision_message = FreelancehuntThreadMessage(
        message_id="msg-revision-limit",
        text="Нужно еще раз поправить текст и отправить обновленную версию.",
        created_at="2026-06-15T10:00:00+03:00",
        author_id="client-1",
        author_type="employer",
        is_own=False,
        raw={"id": "msg-revision-limit"},
    )
    conversation_client = FakeFreelancehuntConversationClient(messages=[revision_message])
    execution_client = FakeExecutionDraftClient(delivery_message="Не должно отправиться.")
    config = replace(
        make_config(tmp_path),
        auto_conversation_enabled=True,
        auto_revision_enabled=True,
        auto_revision_per_order_limit=1,
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
    sent_revision_dir = store.order_dir(order.order_id) / "revisions" / "revision-001"
    sent_revision_dir.mkdir(parents=True)
    (sent_revision_dir / "delivery_message.sent.json").write_text(
        json.dumps({"sent_at": "15.06.2026 09:00 МСК", "message": "v1"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

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
    manual_review = json.loads(
        (store.order_dir(order.order_id) / "revisions" / "manual_review_required.json").read_text(encoding="utf-8")
    )
    assert "лимит правок по заказу исчерпан" in manual_review["reason"]
    revision_summary = json.loads(
        (store.order_dir(order.order_id) / "revisions" / "summary.json").read_text(encoding="utf-8")
    )
    assert revision_summary["sent_count"] == 1
    assert revision_summary["blocked_count"] == 1
    assert revision_summary["latest_status"] == "blocked"
    assert "лимит правок по заказу исчерпан" in revision_summary["latest_reason"]
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
    assert (store.order_dir(order.order_id) / "order_run_report.json").exists()


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
    assert delivered
    assert delivered[0][0] == order.order_id
    assert "Здравствуйте! Результат готов к проверке." in delivered[0][1]
    assert "Пакет результата" in delivered[0][1]
    assert answers == ["Результат отправлен заказчику."]


def test_handle_order_callback_blocks_delivery_when_quality_failed(tmp_path):
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
    order_dir = store.order_dir(order.order_id)
    outbox = order_dir / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "delivery_message.md").write_text("Здравствуйте! Результат готов к проверке.\n", encoding="utf-8")
    quality_dir = order_dir / "quality"
    quality_dir.mkdir()
    (quality_dir / "latest.json").write_text(
        json.dumps({"passed": False, "local": {"issues": [{"code": "missing_readme"}]}}),
        encoding="utf-8",
    )

    updated = handle_order_callback(
        callback_data=f"o:as:{order.order_id}",
        store=store,
        answer=answers.append,
        send_delivery=lambda order, text: delivered.append((order.order_id, text)),
    )

    assert updated is not None
    assert updated.status == OrderStatus.AWAITING_DELIVERY_APPROVAL
    assert delivered == []
    assert "QA не пройдена" in answers[-1]


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
    assert delivered
    assert delivered[0][0] == order.order_id
    assert "Результат готов." in delivered[0][1]
    assert "Пакет результата" in delivered[0][1]
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


def test_run_local_agent_retires_disabled_freelancehunt_order_without_ai(tmp_path):
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_source_enabled=False,
        rss_feeds=["https://www.fl.ru/rss/projects.xml"],
    )
    store = OrderStore(config.orders_path)
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/bot/1639000.html",
        url="https://freelancehunt.com/project/bot/1639000.html",
        text="Нужен Telegram-бот, бюджет 12 000 руб.",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    store.save_order(order)
    client = FakeAutopilotClient(safe_autopilot_result())

    run_local_agent_once(
        config,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: None,
        autopilot_client=client,
    )

    assert store.load_order(order.order_id).status == OrderStatus.SKIPPED
    assert client.orders == []
    assert not (store.order_dir(order.order_id) / "autopilot" / "analysis.json").exists()


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


def test_handle_order_callback_writes_send_failure_diagnostics(tmp_path):
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
    order_dir = store.order_dir(order.order_id)
    (order_dir / "autopilot").mkdir(parents=True)
    (order_dir / "autopilot" / "outreach.md").write_text(
        "Здравствуйте! Готов выполнить Telegram-бота для заявок.\n",
        encoding="utf-8",
    )

    def failing_send_outreach(order, text):
        error = requests.HTTPError("422 Client Error")
        error.response = type("Response", (), {"status_code": 422})()
        raise error

    updated = handle_order_callback(
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
        send_outreach=failing_send_outreach,
    )

    assert updated is not None
    assert updated.status == OrderStatus.SEND_FAILED
    payload = json.loads((order_dir / "outbox" / "send_failure.json").read_text(encoding="utf-8"))
    assert payload["error"] == "HTTPError"
    assert payload["status_code"] == 422
    assert payload["endpoint"] == "/projects/123456/bids"
    assert answers == ["Отклик не отправлен: HTTPError."]


def test_handle_order_callback_closes_order_when_freelancehunt_project_is_gone(tmp_path):
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
    order_dir = store.order_dir(order.order_id)
    (order_dir / "autopilot").mkdir(parents=True)
    (order_dir / "autopilot" / "outreach.md").write_text(
        "Здравствуйте! Готов выполнить Telegram-бота для заявок.\n",
        encoding="utf-8",
    )

    def gone_send_outreach(order, text):
        error = requests.HTTPError("410 Client Error")
        error.response = type("Response", (), {"status_code": 410})()
        raise error

    updated = handle_order_callback(
        callback_data=f"o:ao:{order.order_id}",
        store=store,
        answer=answers.append,
        send_outreach=gone_send_outreach,
    )

    assert updated is not None
    assert updated.status == OrderStatus.CLOSED
    payload = json.loads((order_dir / "outbox" / "send_failure.json").read_text(encoding="utf-8"))
    assert payload["status_code"] == 410
    assert answers == ["Отклик не отправлен: HTTPError."]


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
