from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Protocol

from vacancy_monitor.agent import FIRST_OUTREACH_DRAFT, handle_matched_post
from vacancy_monitor.autopilot import OpenAIResponsesClient, run_order_autopilot
from vacancy_monitor.cli import MonitorSummary, run_monitor
from vacancy_monitor.config import Config
from vacancy_monitor.conversation import (
    build_thread_notification,
    find_order_for_thread,
    sync_thread_to_order,
    write_thread_reply_draft,
    write_thread_reply_sent_record,
)
from vacancy_monitor.customer_intent import CustomerIntent, classify_customer_messages
from vacancy_monitor.delivery_adapter import DeliveryPayload, build_delivery_payload
from vacancy_monitor.execution import (
    ExecutionDraftPackage,
    prepare_execution_workspace,
    read_execution_draft_package,
    replace_execution_draft_package,
    write_execution_draft_package,
)
from vacancy_monitor.execution_verifier import DockerExecutionVerifier, VerificationStatus
from vacancy_monitor.execution_runtime import write_execution_runtime_health
from vacancy_monitor.email_inbound import (
    EmailInboundMessage,
    IMAPEmailClient,
    build_email_notification,
    find_order_for_email,
    sync_email_messages_to_order,
    write_email_reply_draft,
    write_email_reply_sent_record,
)
from vacancy_monitor.email_outreach import SMTPOutreachClient
from vacancy_monitor.email_transport_health import (
    EmailTransportHealth,
    probe_email_transport,
    write_email_transport_health_report,
)
from vacancy_monitor.freelancehunt import (
    FreelancehuntBid,
    FreelancehuntClient,
    FreelancehuntMyBid,
    FreelancehuntThread,
    FreelancehuntThreadMessage,
)
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.job_queue import AgentJobQueue
from vacancy_monitor.job_worker import (
    is_retryable_job_error,
    retry_delay_seconds,
    write_dead_letter,
    write_job_attempt,
    write_queue_health,
)
from vacancy_monitor.marketplace_planner import build_marketplace_plan, write_marketplace_plan_report
from vacancy_monitor.order_models import MOSCOW_TZ, Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_run_report import write_order_run_report
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import (
    YooKassaPaymentClient,
    append_payment_ledger_event,
    build_static_payment_request,
    format_payment_block,
    write_payment_request,
)
from vacancy_monitor.public_sources import (
    PUBLIC_SOURCE_URLS,
    PublicSourceHealth,
    fetch_public_project_posts,
    probe_public_source,
    write_public_source_health_report,
)
from vacancy_monitor.quality import AIQualityReview, check_generated_package
from vacancy_monitor.sources import fetch_channel_posts, fetch_rss_posts as fetch_rss_feed_posts
from vacancy_monitor.status_report import (
    audit_freelancehunt_api,
    build_status_report_text,
    mark_status_report_sent,
    should_send_status_report,
    write_status_report_snapshot,
)
from vacancy_monitor.task_router import route_order_task
from vacancy_monitor.telegram import answer_callback_query, get_updates, send_telegram_message
from vacancy_monitor.telegram_control import CallbackAction, build_order_keyboard, parse_callback_data, resolve_transition


class AutopilotClient(Protocol):
    def analyze_order(self, order: Order):
        ...


class ConversationReplyClient(Protocol):
    def draft_thread_reply(self, order: Order, messages: list[FreelancehuntThreadMessage]) -> str:
        ...


class ExecutionDraftClient(Protocol):
    def draft_execution_package(
        self,
        order: Order,
        conversation_text: str,
        execution_context: str,
    ) -> ExecutionDraftPackage:
        ...

    def review_execution_package(
        self,
        order: Order,
        conversation_text: str,
        package: ExecutionDraftPackage,
    ) -> AIQualityReview:
        ...

    def repair_execution_package(
        self,
        order: Order,
        conversation_text: str,
        package: ExecutionDraftPackage,
        repair_instructions_ru: str,
    ) -> ExecutionDraftPackage:
        ...


class FreelancehuntConversationClient(Protocol):
    def list_threads(self) -> list[FreelancehuntThread]:
        ...

    def get_thread_messages(self, thread_id: str) -> list[FreelancehuntThreadMessage]:
        ...

    def mark_thread_read(self, thread_id: str) -> dict:
        ...

    def add_thread_message(self, *, thread_id: str, message_html: str) -> dict:
        ...

    def list_my_bids(self) -> list[FreelancehuntMyBid]:
        ...


class EmailInboundClient(Protocol):
    def list_unseen_messages(self) -> list[EmailInboundMessage]:
        ...

    def mark_seen(self, message_id: str) -> None:
        ...


def run_local_agent_once(
    config: Config,
    *,
    fetch_posts: Callable[[str], list[Post]] = fetch_channel_posts,
    fetch_rss_posts: Callable[[str], list[Post]] | None = fetch_rss_feed_posts,
    fetch_public_posts: Callable[[str], list[Post]] | None = fetch_public_project_posts,
    probe_public: Callable[[str], PublicSourceHealth] = probe_public_source,
    send_message: Callable[..., None] | None = None,
    autopilot_client: AutopilotClient | None = None,
    send_outreach: Callable[[Order, str], None] | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
    freelancehunt_client: FreelancehuntConversationClient | None = None,
    email_inbound_client: EmailInboundClient | None = None,
    conversation_reply_client: ConversationReplyClient | None = None,
    execution_draft_client: ExecutionDraftClient | None = None,
    probe_email_transport_func: Callable[[Config], EmailTransportHealth] = probe_email_transport,
    process_jobs: bool = True,
) -> MonitorSummary:
    store = OrderStore(config.orders_path)
    if config.execution_verify_enabled:
        try:
            write_execution_runtime_health(
                path=config.orders_path / "reports" / "execution_runtime_health.json",
                python_image=config.execution_python_image,
                node_image=config.execution_node_image,
            )
        except OSError:
            pass
    queue = None
    recovered_leases = 0
    queue_enabled = bool(config.agent_queue_enabled and config.auto_mode != "off" and config.openai_api_key)
    if queue_enabled:
        queue = AgentJobQueue(config.agent_queue_path or (config.orders_path / "agent_jobs.sqlite3"))
        recovered_leases = queue.release_expired_leases(now=datetime.now(tz=UTC))
        _reconcile_agent_jobs(config=config, store=store, queue=queue)
    public_health: list[PublicSourceHealth] = []
    public_posts: dict[str, list[Post]] = {}
    public_errors: dict[str, Exception] = {}

    if fetch_public_posts is not None:
        for source in config.public_project_sources:
            try:
                posts = fetch_public_posts(source)
                public_posts[source] = posts
                public_health.append(
                    PublicSourceHealth(
                        source=source,
                        url=PUBLIC_SOURCE_URLS.get(source, ""),
                        checked_at=datetime.now(tz=MOSCOW_TZ).isoformat(),
                        status="available",
                        posts=len(posts),
                    )
                )
            except Exception as exc:
                public_errors[source] = exc
                public_health.append(
                    PublicSourceHealth(
                        source=source,
                        url=PUBLIC_SOURCE_URLS.get(source, ""),
                        checked_at=datetime.now(tz=MOSCOW_TZ).isoformat(),
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
    for source in config.public_source_probes:
        public_health.append(probe_public(source))
    if config.public_project_sources or config.public_source_probes:
        write_public_source_health_report(
            config.orders_path / "reports" / "public_sources_health.json",
            public_health,
        )
    email_health = _maybe_probe_email_transport(config=config, probe_email_transport_func=probe_email_transport_func)
    if _should_write_marketplace_plan(config):
        marketplace_plan = build_marketplace_plan(config=config, public_health=public_health, email_health=email_health)
        write_marketplace_plan_report(config.orders_path / "reports", marketplace_plan)

    def tracked_public_fetch(source: str) -> list[Post]:
        if source in public_errors:
            raise public_errors[source]
        return public_posts.get(source, [])
    sender = send_message or (
        lambda text, reply_markup=None: send_telegram_message(
            config.bot_token,
            config.chat_id,
            text,
            reply_markup=reply_markup,
        )
    )
    outreach_sender = send_outreach or (
        (lambda order, text: _send_marketplace_outreach(config, order, text))
        if config.freelancehunt_api_token or (config.smtp_host and config.smtp_from)
        else None
    )

    def on_match(post: Post, result: MatchResult) -> None:
        order = handle_matched_post(
            post=post,
            result=result,
            store=store,
            send_approval=(
                (lambda text, reply_markup: None)
                if config.auto_mode == "autopilot"
                else (lambda text, reply_markup: sender(text, reply_markup=reply_markup))
            ),
        )
        if queue is not None:
            _enqueue_advance_order(config=config, queue=queue, order=order)
        else:
            _maybe_run_autopilot(
                config=config,
                order=order,
                store=store,
                sender=sender,
                autopilot_client=autopilot_client,
                send_outreach=outreach_sender,
                email_health=email_health,
            )

    summary = run_monitor(
        channels=config.channels,
        rss_feeds=config.rss_feeds,
        public_project_sources=config.public_project_sources,
        state_path=config.state_path,
        fetch_posts=fetch_posts,
        fetch_rss_posts=fetch_rss_posts,
        fetch_public_posts=tracked_public_fetch,
        send_message=lambda text: sender(text),
        send_first_run=config.send_first_run,
        on_match=on_match,
    )
    if queue is not None:
        if process_jobs:
            _process_agent_jobs(
                config=config,
                store=store,
                queue=queue,
                sender=sender,
                autopilot_client=autopilot_client,
                send_outreach=outreach_sender,
                recovered_leases=recovered_leases,
                email_health=email_health,
            )
        else:
            write_queue_health(
                path=config.orders_path / "reports" / "job_queue_health.json",
                queue=queue,
                recovered_leases=recovered_leases,
                now=datetime.now(tz=UTC),
            )
    else:
        _process_pending_autopilot_orders(
            config=config,
            store=store,
            sender=sender,
            autopilot_client=autopilot_client,
            send_outreach=outreach_sender,
            email_health=email_health,
        )
    _process_pending_auto_outreach_orders(
        config=config,
        store=store,
        sender=sender,
        send_outreach=outreach_sender,
        email_health=email_health,
    )
    _sync_freelancehunt_conversations(
        config=config,
        store=store,
        sender=sender,
        freelancehunt_client=freelancehunt_client,
        conversation_reply_client=conversation_reply_client,
        execution_draft_client=execution_draft_client,
        send_delivery=send_delivery,
    )
    _sync_email_conversations(
        config=config,
        store=store,
        sender=sender,
        email_health=email_health,
        email_client=email_inbound_client,
        conversation_reply_client=conversation_reply_client,
        execution_draft_client=execution_draft_client,
        send_email=outreach_sender,
        send_delivery=send_delivery,
    )
    _sync_freelancehunt_bids(
        config=config,
        store=store,
        sender=sender,
        freelancehunt_client=freelancehunt_client,
    )
    _write_order_run_reports(store=store)
    _maybe_send_status_report(
        config=config,
        store=store,
        sender=sender,
        freelancehunt_client=freelancehunt_client,
    )
    return summary


def _write_order_run_reports(*, store: OrderStore) -> None:
    for order in store.list_orders():
        try:
            write_order_run_report(store=store, order=order)
        except OSError:
            continue


def _enqueue_advance_order(*, config: Config, queue: AgentJobQueue, order: Order) -> None:
    queue.enqueue(
        order_id=order.order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{order.order_id}",
        max_attempts=config.agent_job_max_attempts,
        now=datetime.now(tz=UTC),
    )


def _should_write_marketplace_plan(config: Config) -> bool:
    return (
        config.auto_mode != "off"
        or bool(config.public_project_sources)
        or bool(config.public_source_probes)
        or config.orders_path.exists()
    )


def _maybe_probe_email_transport(
    *,
    config: Config,
    probe_email_transport_func: Callable[[Config], EmailTransportHealth],
) -> EmailTransportHealth | None:
    if not (config.smtp_host or config.imap_host):
        return None
    report = probe_email_transport_func(config)
    write_email_transport_health_report(config.orders_path / "reports" / "email_transport_health.json", report)
    return report


def _reconcile_agent_jobs(*, config: Config, store: OrderStore, queue: AgentJobQueue) -> None:
    for order in store.list_orders():
        if order.status == OrderStatus.AWAITING_RESPONSE_APPROVAL:
            queue.reopen_dead(
                idempotency_key=f"advance_order:{order.order_id}",
                max_attempts=config.agent_job_max_attempts,
                now=datetime.now(tz=UTC),
            )
            _enqueue_advance_order(config=config, queue=queue, order=order)


def _process_agent_jobs(
    *,
    config: Config,
    store: OrderStore,
    queue: AgentJobQueue,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
    send_outreach: Callable[[Order, str], None] | None,
    recovered_leases: int,
    email_health: EmailTransportHealth | None = None,
) -> None:
    for _ in range(config.agent_jobs_per_cycle):
        claimed_at = datetime.now(tz=UTC)
        job = queue.claim_next(lease_seconds=config.agent_job_lease_seconds, now=claimed_at)
        if job is None:
            break
        try:
            order = store.load_order(job.order_id)
            if job.kind != "advance_order":
                raise ValueError(f"unsupported job kind: {job.kind}")
            if order.status != OrderStatus.AWAITING_RESPONSE_APPROVAL:
                queue.complete(job.job_id, now=datetime.now(tz=UTC))
                write_job_attempt(
                    order_dir=store.order_dir(order.order_id),
                    job=job,
                    outcome="already_advanced",
                    error=None,
                    now=datetime.now(tz=UTC),
                )
                continue
            if _order_is_stale(order, max_age_hours=config.auto_outreach_max_age_hours):
                store.update_status(order.order_id, OrderStatus.SKIPPED)
                queue.complete(job.job_id, now=datetime.now(tz=UTC))
                write_job_attempt(
                    order_dir=store.order_dir(order.order_id),
                    job=job,
                    outcome="stale_skipped",
                    error=None,
                    now=datetime.now(tz=UTC),
                )
                continue
            analysis_path = store.order_dir(order.order_id) / "autopilot" / "analysis.json"
            if analysis_path.exists():
                if config.auto_mode == "autopilot":
                    store.update_status(order.order_id, OrderStatus.SKIPPED)
                queue.complete(job.job_id, now=datetime.now(tz=UTC))
                write_job_attempt(
                    order_dir=store.order_dir(order.order_id),
                    job=job,
                    outcome="existing_analysis",
                    error=None,
                    now=datetime.now(tz=UTC),
                )
                continue
            _maybe_run_autopilot(
                config=config,
                order=order,
                store=store,
                sender=sender,
                autopilot_client=autopilot_client,
                send_outreach=send_outreach,
                email_health=email_health,
                raise_on_error=True,
            )
        except Exception as exc:
            terminal = not is_retryable_job_error(exc) or job.attempts >= job.max_attempts
            if terminal:
                queue.fail(job.job_id, exc, now=datetime.now(tz=UTC))
                write_job_attempt(
                    order_dir=store.order_dir(job.order_id),
                    job=job,
                    outcome="dead",
                    error=exc,
                    now=datetime.now(tz=UTC),
                )
                write_dead_letter(
                    order_dir=store.order_dir(job.order_id),
                    job=job,
                    error=exc,
                    now=datetime.now(tz=UTC),
                )
                _safe_notify(
                    sender,
                    f"Фоновая обработка заказа {job.order_id} окончательно остановлена: {type(exc).__name__}.",
                )
            else:
                queue.retry(
                    job.job_id,
                    exc,
                    delay_seconds=retry_delay_seconds(job.attempts, job.job_id),
                    now=datetime.now(tz=UTC),
                )
                write_job_attempt(
                    order_dir=store.order_dir(job.order_id),
                    job=job,
                    outcome="retry",
                    error=exc,
                    now=datetime.now(tz=UTC),
                )
            continue
        queue.complete(job.job_id, now=datetime.now(tz=UTC))
        write_job_attempt(
            order_dir=store.order_dir(job.order_id),
            job=job,
            outcome="succeeded",
            error=None,
            now=datetime.now(tz=UTC),
        )
    write_queue_health(
        path=config.orders_path / "reports" / "job_queue_health.json",
        queue=queue,
        recovered_leases=recovered_leases,
        now=datetime.now(tz=UTC),
    )


def _process_pending_autopilot_orders(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
    send_outreach: Callable[[Order, str], None] | None,
    email_health: EmailTransportHealth | None = None,
) -> None:
    if config.auto_mode == "off" or not config.openai_api_key:
        return
    for order in store.list_orders():
        if order.status != OrderStatus.AWAITING_RESPONSE_APPROVAL:
            continue
        if _order_is_stale(order, max_age_hours=config.auto_outreach_max_age_hours):
            store.update_status(order.order_id, OrderStatus.SKIPPED)
            continue
        if (store.order_dir(order.order_id) / "autopilot" / "analysis.json").exists():
            if config.auto_mode == "autopilot":
                store.update_status(order.order_id, OrderStatus.SKIPPED)
            continue
        _maybe_run_autopilot(
            config=config,
            order=order,
            store=store,
            sender=sender,
            autopilot_client=autopilot_client,
            send_outreach=send_outreach,
            email_health=email_health,
        )


def _process_pending_auto_outreach_orders(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    send_outreach: Callable[[Order, str], None] | None,
    email_health: EmailTransportHealth | None = None,
) -> None:
    if not config.auto_outreach_enabled:
        return
    for order in store.list_orders():
        if order.status == OrderStatus.SEND_FAILED:
            order = _recover_send_failed_outreach(
                config=config,
                order=order,
                store=store,
                sender=sender,
                send_outreach=send_outreach,
                email_health=email_health,
            )
        if order.status == OrderStatus.DRAFT_READY:
            _maybe_auto_send_outreach(
                config=config,
                order=order,
                store=store,
                sender=sender,
                send_outreach=send_outreach,
                email_health=email_health,
            )


def _recover_send_failed_outreach(
    *,
    config: Config,
    order: Order,
    store: OrderStore,
    sender: Callable[..., None],
    send_outreach: Callable[[Order, str], None] | None,
    email_health: EmailTransportHealth | None = None,
) -> Order:
    status_code = _read_outreach_failure_status_code(store=store, order=order)
    if status_code == 410:
        updated = store.update_status(order.order_id, OrderStatus.CLOSED)
        _safe_notify(sender, f"Заказ {order.order_id} закрыт: площадка вернула 410 Gone при отклике.")
        return updated
    if not _is_retryable_outreach_failure(status_code):
        return order
    retry_order = replace(order, status=OrderStatus.DRAFT_READY, updated_at=format_moscow_time())
    store.save_order(retry_order)
    return _maybe_auto_send_outreach(
            config=config,
            order=retry_order,
            store=store,
            sender=sender,
            send_outreach=send_outreach,
            email_health=email_health,
        )


def _read_outreach_failure_status_code(*, store: OrderStore, order: Order) -> int | None:
    path = store.order_dir(order.order_id) / "outbox" / "send_failure.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("status_code")
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, int) else None


def _is_retryable_outreach_failure(status_code: int | None) -> bool:
    if status_code is None:
        return True
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _sync_freelancehunt_bids(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    freelancehunt_client: FreelancehuntConversationClient | None = None,
) -> None:
    if not config.auto_payment_watch_enabled or not config.freelancehunt_api_token:
        return

    client = freelancehunt_client or FreelancehuntClient(api_token=config.freelancehunt_api_token)
    try:
        bids = client.list_my_bids()
    except Exception as exc:
        _write_bid_watch_error(store=store, exc=exc)
        return

    for bid in bids:
        order = _find_order_for_project_id(store, bid.project_id)
        if order is None:
            continue
        _write_bid_status(store=store, order=order, bid=bid)
        if bid.is_winner and order.status == OrderStatus.OUTREACH_SENT:
            order = store.update_status(order.order_id, OrderStatus.DISCOVERY)
            _safe_notify(
                sender,
                (
                    "Ставка выбрана заказчиком на Freelancehunt.\n\n"
                    f"ID: {order.order_id}\n"
                    f"Проект: {bid.project_id or 'не указан'}\n\n"
                    "Заказ автоматически переведен в работу."
                ),
            )
        if order.status == OrderStatus.PAYMENT_REQUESTED and bid.is_winner and _project_is_completed(bid):
            updated = store.update_status(order.order_id, OrderStatus.CLOSED)
            append_payment_ledger_event(
                store=store,
                order=updated,
                event="payment_confirmed",
                provider="freelancehunt_safe",
                amount_rub=_payment_amount_rub(updated),
                status="confirmed",
                payment_id=bid.bid_id,
            )
            _safe_notify(
                sender,
                (
                    "Проект завершен на Freelancehunt.\n\n"
                    f"ID: {updated.order_id}\n"
                    f"Ставка: {bid.bid_id or 'не указана'}\n"
                    f"Статус проекта: {bid.project_status or 'не указан'}\n\n"
                    "Заказ закрыт в локальном агенте. Проверьте поступление выплаты на балансе биржи."
                ),
            )


def _find_order_for_project_id(store: OrderStore, project_id: str | None) -> Order | None:
    if not project_id:
        return None
    for order in store.list_orders():
        if order.contact and order.contact.channel == "freelancehunt" and order.contact.value == project_id:
            return order
        if f"/{project_id}.html" in order.source_url or f"/{project_id}" in order.source_url:
            return order
    return None


def _write_bid_status(*, store: OrderStore, order: Order, bid: FreelancehuntMyBid) -> None:
    path = store.order_dir(order.order_id) / "payment" / "freelancehunt_bid.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "checked_at": format_moscow_time(),
                "bid_id": bid.bid_id,
                "project_id": bid.project_id,
                "status": bid.status,
                "is_winner": bid.is_winner,
                "project_status": bid.project_status,
                "raw": bid.raw,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_bid_watch_error(*, store: OrderStore, exc: Exception) -> None:
    path = store.orders_dir / "reports" / "freelancehunt_bid_watch_error.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    payload = {
        "checked_at": format_moscow_time(),
        "error": type(exc).__name__,
        "status_code": status_code,
    }
    payload["endpoint"] = "/my/bids"
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_outreach_send_failure(*, store: OrderStore, order: Order, exc: Exception) -> None:
    path = store.order_dir(order.order_id) / "outbox" / "send_failure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    payload = {
        "checked_at": format_moscow_time(),
        "error": type(exc).__name__,
        "status_code": status_code,
    }
    if order.contact and order.contact.channel == "freelancehunt":
        payload["endpoint"] = f"/projects/{order.contact.value}/bids"
    detail = str(exc).strip()
    if detail:
        payload["detail"] = detail[:200]
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _outreach_failure_status(exc: Exception) -> OrderStatus:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 410:
        return OrderStatus.CLOSED
    return OrderStatus.SEND_FAILED


def _project_is_completed(bid: FreelancehuntMyBid) -> bool:
    text = (bid.project_status or "").lower()
    markers = [
        "completed",
        "complete",
        "closed",
        "done",
        "finished",
        "paid",
        "accepted",
        "success",
        "выполн",
        "закры",
        "оплач",
        "принят",
    ]
    return any(marker in text for marker in markers)


def _payment_amount_rub(order: Order) -> int:
    if order.price_rub and order.price_rub > 0:
        return order.price_rub
    text = order.original_text.lower().replace("\xa0", " ")
    match = re.search(r"(\d[\d\s.,]*)\s*(?:₽|руб|р\.)", text)
    if not match:
        return 0
    return int(re.sub(r"\D", "", match.group(1)) or "0")


def _maybe_send_status_report(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    freelancehunt_client: FreelancehuntConversationClient | None = None,
) -> None:
    if not config.auto_status_report_enabled:
        return
    if not should_send_status_report(store=store, interval_minutes=config.auto_status_report_interval_minutes):
        return
    client = freelancehunt_client
    if client is None and config.freelancehunt_api_token:
        client = FreelancehuntClient(api_token=config.freelancehunt_api_token)
    audit = audit_freelancehunt_api(store=store, client=client)
    text = build_status_report_text(store=store, audit=audit)
    write_status_report_snapshot(store=store, audit=audit, text=text)
    _safe_notify(sender, text)
    mark_status_report_sent(store=store)


def _sync_freelancehunt_conversations(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    freelancehunt_client: FreelancehuntConversationClient | None = None,
    conversation_reply_client: ConversationReplyClient | None = None,
    execution_draft_client: ExecutionDraftClient | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
) -> None:
    if not config.auto_conversation_enabled or not config.freelancehunt_api_token:
        return

    client = freelancehunt_client or FreelancehuntClient(api_token=config.freelancehunt_api_token)
    reply_client = conversation_reply_client
    if reply_client is None and config.openai_api_key:
        reply_client = OpenAIResponsesClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url,
        )
    draft_client = execution_draft_client
    if draft_client is None and config.openai_api_key:
        draft_client = OpenAIResponsesClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url,
        )
    try:
        threads = client.list_threads()
    except Exception as exc:
        _safe_notify(sender, f"Синхронизация переписки Freelancehunt не выполнена: {type(exc).__name__}.")
        return

    for thread in threads:
        if not thread.is_unread:
            continue
        order = find_order_for_thread(store, thread)
        if order is None:
            continue
        try:
            messages = client.get_thread_messages(thread.thread_id)
            updated_order = sync_thread_to_order(store=store, order=order, thread=thread, messages=messages)
            client.mark_thread_read(thread.thread_id)
        except Exception as exc:
            _safe_notify(
                sender,
                f"Ответ заказчика по заказу {order.order_id} не синхронизирован: {type(exc).__name__}.",
            )
            continue
        _safe_notify(sender, build_thread_notification(order=updated_order, thread=thread, messages=messages))

        def send_thread_delivery(order: Order, text: str, *, thread_id: str = thread.thread_id) -> None:
            client.add_thread_message(thread_id=thread_id, message_html=text)

        if _maybe_record_customer_payment_signal(
            store=store,
            order=updated_order,
            messages=[message.text for message in messages if not message.is_own and message.text],
            sender=sender,
        ):
            continue

        if _maybe_process_revision_request(
            config=config,
            store=store,
            order=updated_order,
            thread=thread,
            messages=messages,
            sender=sender,
            execution_draft_client=draft_client,
            send_delivery=send_delivery or send_thread_delivery,
        ):
            continue

        _maybe_draft_thread_reply(
            store=store,
            order=updated_order,
            thread=thread,
            messages=messages,
            sender=sender,
            reply_client=reply_client,
            marketplace_client=client,
            config=config,
        )

        _maybe_prepare_execution_workspace(
            config=config,
            store=store,
            order=updated_order,
            sender=sender,
            execution_draft_client=draft_client,
            send_delivery=send_delivery or send_thread_delivery,
        )


def _sync_email_conversations(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    email_health: EmailTransportHealth | None = None,
    email_client: EmailInboundClient | None = None,
    conversation_reply_client: ConversationReplyClient | None = None,
    execution_draft_client: ExecutionDraftClient | None = None,
    send_email: Callable[[Order, str], None] | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
) -> None:
    if not config.auto_conversation_enabled or not config.imap_host:
        return
    if (
        email_client is None
        and email_health is not None
        and email_health.imap_configured
        and not email_health.imap_reachable
    ):
        _write_email_sync_skipped_report(config=config, reason=f"IMAP недоступен: {email_health.imap_error or 'connection failed'}")
        return

    client = email_client or IMAPEmailClient(
        host=config.imap_host,
        port=config.imap_port,
        username=config.imap_username,
        password=config.imap_password,
        folder=config.imap_folder,
        use_ssl=config.imap_use_ssl,
    )
    reply_client = conversation_reply_client
    if reply_client is None and config.openai_api_key:
        reply_client = OpenAIResponsesClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url,
        )
    draft_client = execution_draft_client
    if draft_client is None and config.openai_api_key:
        draft_client = OpenAIResponsesClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url,
        )

    try:
        messages = client.list_unseen_messages()
    except Exception as exc:
        _safe_notify(sender, f"Синхронизация email-переписки не выполнена: {type(exc).__name__}.")
        return

    for message in messages:
        order = find_order_for_email(store, message)
        if order is None:
            continue
        try:
            updated_order = sync_email_messages_to_order(store=store, order=order, messages=[message])
            client.mark_seen(message.message_id)
        except Exception as exc:
            _safe_notify(sender, f"Email-ответ по заказу {order.order_id} не синхронизирован: {type(exc).__name__}.")
            continue
        _safe_notify(sender, build_email_notification(order=updated_order, messages=[message]))

        thread_messages = [message.as_thread_message()]
        if _maybe_record_customer_payment_signal(
            store=store,
            order=updated_order,
            messages=[message.text],
            sender=sender,
        ):
            continue
        _maybe_draft_email_reply(
            store=store,
            order=updated_order,
            messages=thread_messages,
            recipient=message.from_email,
            sender=sender,
            reply_client=reply_client,
            send_email=send_email,
            config=config,
        )

        _maybe_prepare_execution_workspace(
            config=config,
            store=store,
            order=updated_order,
            sender=sender,
            execution_draft_client=draft_client,
            send_delivery=send_delivery or send_email,
        )


def _maybe_record_customer_payment_signal(
    *,
    store: OrderStore,
    order: Order,
    messages: list[str],
    sender: Callable[..., None],
) -> bool:
    if order.status != OrderStatus.PAYMENT_REQUESTED:
        return False
    intent = classify_customer_messages(messages)
    if intent.intent != CustomerIntent.PAYMENT_SIGNAL:
        return False
    ledger = append_payment_ledger_event(
        store=store,
        order=order,
        event="payment_signal_received",
        provider=order.contact.channel if order.contact else "customer_message",
        amount_rub=_payment_amount_rub(order),
        status="awaiting_confirmation",
    )
    _write_customer_payment_signal(store=store, order=order, messages=messages, ledger=ledger)
    _safe_notify(
        sender,
        (
            "Заказчик сообщил об оплате.\n\n"
            f"ID: {order.order_id}\n"
            f"Сумма по заказу: {_format_rub(_payment_amount_rub(order))}\n"
            "Статус: ожидает подтверждения поступления. Заказ не закрыт автоматически без проверяемого сигнала оплаты."
        ),
    )
    return True


def _write_customer_payment_signal(*, store: OrderStore, order: Order, messages: list[str], ledger: dict) -> None:
    path = store.order_dir(order.order_id) / "payment" / "customer_payment_signal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_at": format_moscow_time(),
                "messages": messages,
                "ledger_status": ledger.get("current_status"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _format_rub(amount: int) -> str:
    return f"{amount:,.0f}".replace(",", " ") + " ₽"


def _write_email_sync_skipped_report(*, config: Config, reason: str) -> None:
    path = config.orders_path / "reports" / "email_sync_skipped.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "checked_at": format_moscow_time(),
                "reason": reason,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _maybe_draft_email_reply(
    *,
    store: OrderStore,
    order: Order,
    messages: list[FreelancehuntThreadMessage],
    recipient: str,
    sender: Callable[..., None],
    reply_client: ConversationReplyClient | None,
    send_email: Callable[[Order, str], None] | None,
    config: Config,
) -> None:
    if reply_client is None or not any((not message.is_own) and message.text for message in messages):
        return
    try:
        reply_text = reply_client.draft_thread_reply(order, messages)
        path = write_email_reply_draft(store=store, order=order, recipient=recipient, reply_text=reply_text)
    except Exception as exc:
        _safe_notify(sender, f"AI-черновик email-ответа по заказу {order.order_id} не создан: {type(exc).__name__}.")
        return
    _safe_notify(
        sender,
        (
            "AI-черновик email-ответа заказчику готов.\n\n"
            f"ID: {order.order_id}\n"
            f"Файл: {path.relative_to(store.order_dir(order.order_id))}\n\n"
            f"{reply_text}"
        ),
    )
    _maybe_auto_send_email_reply(
        config=config,
        store=store,
        order=order,
        messages=messages,
        recipient=recipient,
        reply_text=reply_text,
        sender=sender,
        send_email=send_email,
    )


def _maybe_auto_send_email_reply(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    messages: list[FreelancehuntThreadMessage],
    recipient: str,
    reply_text: str,
    sender: Callable[..., None],
    send_email: Callable[[Order, str], None] | None,
) -> None:
    if not config.auto_reply_enabled:
        return
    if send_email is None:
        _safe_notify(
            sender,
            (
                "Автоотправка email-ответа заблокирована.\n\n"
                f"ID: {order.order_id}\n"
                "Причина: SMTP не настроен\n\n"
                "Черновик сохранен в outbox/."
            ),
        )
        return
    block_reason = _auto_reply_block_reason(config=config, store=store, order=order, messages=messages, reply_text=reply_text)
    if block_reason:
        _safe_notify(
            sender,
            (
                "Автоотправка email-ответа заблокирована.\n\n"
                f"ID: {order.order_id}\n"
                f"Причина: {block_reason}\n\n"
                "Черновик сохранен в outbox/."
            ),
        )
        return
    try:
        send_email(order, reply_text)
        write_email_reply_sent_record(
            store=store,
            order=order,
            recipient=recipient,
            reply_text=reply_text,
            response_payload={"channel": "email", "recipient": recipient},
        )
    except Exception as exc:
        _safe_notify(sender, f"AI-email ответ по заказу {order.order_id} не отправлен: {type(exc).__name__}.")
        return
    _safe_notify(
        sender,
        (
            "AI-ответ отправлен заказчику по email.\n\n"
            f"ID: {order.order_id}\n"
            f"Email: {recipient}"
        ),
    )


def _maybe_draft_thread_reply(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    messages: list[FreelancehuntThreadMessage],
    sender: Callable[..., None],
    reply_client: ConversationReplyClient | None,
    marketplace_client: FreelancehuntConversationClient,
    config: Config,
) -> None:
    if reply_client is None or not any((not message.is_own) and message.text for message in messages):
        return
    try:
        reply_text = reply_client.draft_thread_reply(order, messages)
        path = write_thread_reply_draft(store=store, order=order, thread=thread, reply_text=reply_text)
    except Exception as exc:
        _safe_notify(sender, f"AI-черновик ответа по заказу {order.order_id} не создан: {type(exc).__name__}.")
        return
    _safe_notify(
        sender,
        (
            "AI-черновик ответа заказчику готов.\n\n"
            f"ID: {order.order_id}\n"
            f"Файл: {path.relative_to(store.order_dir(order.order_id))}\n\n"
            f"{reply_text}"
        ),
    )
    _maybe_auto_send_thread_reply(
        config=config,
        store=store,
        order=order,
        thread=thread,
        messages=messages,
        reply_text=reply_text,
        sender=sender,
        marketplace_client=marketplace_client,
    )


def _maybe_auto_send_thread_reply(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    messages: list[FreelancehuntThreadMessage],
    reply_text: str,
    sender: Callable[..., None],
    marketplace_client: FreelancehuntConversationClient,
) -> None:
    if not config.auto_reply_enabled:
        return
    block_reason = _auto_reply_block_reason(config=config, store=store, order=order, messages=messages, reply_text=reply_text)
    if block_reason:
        _safe_notify(
            sender,
            (
                "Автоотправка ответа заблокирована.\n\n"
                f"ID: {order.order_id}\n"
                f"Причина: {block_reason}\n\n"
                "Черновик сохранен в outbox/."
            ),
        )
        return
    try:
        response_payload = marketplace_client.add_thread_message(thread_id=thread.thread_id, message_html=reply_text)
        write_thread_reply_sent_record(
            store=store,
            order=order,
            thread=thread,
            reply_text=reply_text,
            response_payload=response_payload,
        )
    except Exception as exc:
        _safe_notify(sender, f"AI-ответ по заказу {order.order_id} не отправлен: {type(exc).__name__}.")
        return
    _safe_notify(
        sender,
        (
            "AI-ответ отправлен заказчику на Freelancehunt.\n\n"
            f"ID: {order.order_id}\n"
            f"Тред: {thread.thread_id}"
        ),
    )


def _maybe_process_revision_request(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    messages: list[FreelancehuntThreadMessage],
    sender: Callable[..., None],
    execution_draft_client: ExecutionDraftClient | None,
    send_delivery: Callable[[Order, str], None] | None,
) -> bool:
    if not config.auto_revision_enabled or order.status != OrderStatus.PAYMENT_REQUESTED:
        return False
    customer_messages = [message for message in messages if not message.is_own and message.text]
    if not _has_revision_request(customer_messages):
        return False

    revision_text = "\n".join(message.text for message in customer_messages if message.text)
    block_reason = _auto_revision_block_reason(
        config=config,
        store=store,
        order=order,
        messages=customer_messages,
        execution_draft_client=execution_draft_client,
        send_delivery=send_delivery,
    )
    if block_reason:
        _write_revision_manual_review_required(store=store, order=order, thread=thread, reason=block_reason, text=revision_text)
        _safe_notify(
            sender,
            (
                "Автоправка заблокирована.\n\n"
                f"ID: {order.order_id}\n"
                f"Причина: {block_reason}\n\n"
                "Запрос сохранен в revisions/manual_review_required.json."
            ),
        )
        return True

    order_dir = store.order_dir(order.order_id)
    try:
        prepare_execution_workspace(store=store, order=order)
        conversation_text = _read_optional_text(order_dir / "conversation.md")
        execution_context = _read_execution_context(order_dir / "execution")
        package = execution_draft_client.draft_execution_package(
            order,
            conversation_text,
            f"{execution_context}\n\n# Запрос правок\n\n{revision_text}".strip(),
        )
        replace_execution_draft_package(store=store, order=order, package=package)
        if config.auto_quality_enabled and not _run_delivery_quality_gate(
            config=config,
            store=store,
            order=order,
            sender=sender,
            quality_client=execution_draft_client,
        ):
            return True
        package = read_execution_draft_package(store=store, order=order)
        revision_dir = _write_revision_package(store=store, order=order, thread=thread, package=package, text=revision_text)
        delivery_text = package.delivery_message_ru
        response_payload = send_delivery(order, delivery_text)
        _write_revision_sent_record(revision_dir=revision_dir, text=delivery_text, response_payload=response_payload)
        _write_revision_summary_event(
            store=store,
            order=order,
            thread=thread,
            status="sent",
            text=revision_text,
            revision_dir_name=revision_dir.name,
        )
    except Exception as exc:
        _write_revision_manual_review_required(
            store=store,
            order=order,
            thread=thread,
            reason=type(exc).__name__,
            text=revision_text,
        )
        _safe_notify(sender, f"Автоправка по заказу {order.order_id} не выполнена: {type(exc).__name__}.")
        return True

    store.update_status(order.order_id, OrderStatus.PAYMENT_REQUESTED)
    _safe_notify(
        sender,
        (
            "Правки автоматически внесены и отправлены заказчику.\n\n"
            f"ID: {order.order_id}\n"
            f"Тред: {thread.thread_id}\n"
            "Статус: снова ожидаем оплату / приемку."
        ),
    )
    return True


def _has_revision_request(messages: list[FreelancehuntThreadMessage]) -> bool:
    result = classify_customer_messages([message.text for message in messages if message.text])
    return result.intent in {CustomerIntent.REVISION_REQUEST, CustomerIntent.RISKY_REQUEST}


def _auto_revision_block_reason(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    messages: list[FreelancehuntThreadMessage],
    execution_draft_client: ExecutionDraftClient | None,
    send_delivery: Callable[[Order, str], None] | None,
) -> str | None:
    if order.risks:
        return "у заказа есть риск-флаги"
    if execution_draft_client is None:
        return "нет AI-клиента для подготовки правок"
    if send_delivery is None:
        return "нет подключенного канала отправки правок"
    if _auto_revision_count_for_order(store=store, order=order) >= config.auto_revision_per_order_limit:
        return "лимит правок по заказу исчерпан"
    if _auto_revision_count_today(store) >= config.auto_revision_daily_limit:
        return "дневной лимит автоправок исчерпан"
    combined_text = "\n".join(message.text for message in messages if message.text).lower()
    for term in _dangerous_terms():
        if term in combined_text:
            return f"опасный маркер: {term}"
    return None


def _auto_revision_count_today(store: OrderStore) -> int:
    today_prefix = format_moscow_time().split(" ", 1)[0]
    count = 0
    for path in store.orders_dir.glob("*/revisions/*/delivery_message.sent.json"):
        try:
            if today_prefix in path.read_text(encoding="utf-8"):
                count += 1
        except OSError:
            continue
    return count


def _auto_revision_count_for_order(*, store: OrderStore, order: Order) -> int:
    revisions_dir = store.order_dir(order.order_id) / "revisions"
    return len(list(revisions_dir.glob("revision-*/delivery_message.sent.json")))


def _write_revision_package(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    package: ExecutionDraftPackage,
    text: str,
):
    revisions_dir = store.order_dir(order.order_id) / "revisions"
    revision_dir = revisions_dir / f"revision-{len(list(revisions_dir.glob('revision-*'))) + 1:03d}"
    files_dir = revision_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (revision_dir / "request.md").write_text(text.strip() + "\n", encoding="utf-8")
    (revision_dir / "summary.md").write_text(package.summary_ru.strip() + "\n", encoding="utf-8")
    (revision_dir / "delivery_message.md").write_text(package.delivery_message_ru.strip() + "\n", encoding="utf-8")
    (revision_dir / "thread.json").write_text(
        json.dumps(
            {
                "thread_id": thread.thread_id,
                "project_id": thread.project_id,
                "created_at": format_moscow_time(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for name, content in package.files.items():
        safe_name = name.replace("/", "_").replace("\\", "_").strip() or "result.txt"
        (files_dir / safe_name).write_text(content, encoding="utf-8")
    return revision_dir


def _write_revision_sent_record(*, revision_dir, text: str, response_payload) -> None:
    (revision_dir / "delivery_message.sent.json").write_text(
        json.dumps(
            {
                "sent_at": format_moscow_time(),
                "message": text,
                "response": response_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_revision_summary_event(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    status: str,
    reason: str = "",
    text: str = "",
    revision_dir_name: str | None = None,
) -> None:
    revisions_dir = store.order_dir(order.order_id) / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)
    path = revisions_dir / "summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        summary = {}
    events = list(summary.get("events", []))
    event = {
        "created_at": format_moscow_time(),
        "status": status,
        "thread_id": thread.thread_id,
        "project_id": thread.project_id,
        "reason": reason,
        "request": text,
    }
    if revision_dir_name:
        event["revision_dir"] = revision_dir_name
    events.append(event)
    summary = {
        "order_id": order.order_id,
        "sent_count": _auto_revision_count_for_order(store=store, order=order),
        "blocked_count": sum(1 for item in events if item.get("status") == "blocked"),
        "latest_status": status,
        "latest_reason": reason,
        "updated_at": format_moscow_time(),
        "events": events,
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_revision_manual_review_required(
    *,
    store: OrderStore,
    order: Order,
    thread: FreelancehuntThread,
    reason: str,
    text: str,
) -> None:
    path = store.order_dir(order.order_id) / "revisions" / "manual_review_required.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_at": format_moscow_time(),
                "thread_id": thread.thread_id,
                "project_id": thread.project_id,
                "reason": reason,
                "request": text,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_revision_summary_event(store=store, order=order, thread=thread, status="blocked", reason=reason, text=text)


def _auto_reply_block_reason(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    messages: list[FreelancehuntThreadMessage],
    reply_text: str,
) -> str | None:
    if order.risks:
        return "у заказа есть риск-флаги"
    if order.status not in {OrderStatus.OUTREACH_SENT, OrderStatus.DISCOVERY, OrderStatus.DRAFT_READY}:
        return f"статус {order.status.value} не разрешен для автоответа"
    if _auto_reply_count_today(store) >= config.auto_reply_daily_limit:
        return "дневной лимит автоответов исчерпан"
    combined_text = "\n".join([reply_text, *[message.text for message in messages if message.text]]).lower()
    for term in _dangerous_terms():
        if term in combined_text:
            return f"опасный маркер: {term}"
    return None


def _dangerous_terms() -> list[str]:
    return [
        "логин и пароль",
        "логин/пароль",
        "пароль от",
        "seed",
        "private key",
        "приватный ключ",
        "обойти лимит",
        "обход лимитов",
        "накрут",
        "фишинг",
        "вредонос",
        "мимо безопасной сделки",
        "вне безопасной сделки",
        "без безопасной сделки",
    ]


def _auto_reply_count_today(store: OrderStore) -> int:
    today_prefix = format_moscow_time().split(" ", 1)[0]
    count = 0
    for path in store.orders_dir.glob("*/outbox/freelancehunt_reply_*.sent.json"):
        try:
            if today_prefix in path.read_text(encoding="utf-8"):
                count += 1
        except OSError:
            continue
    return count


def _maybe_prepare_execution_workspace(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    sender: Callable[..., None],
    execution_draft_client: ExecutionDraftClient | None,
    send_delivery: Callable[[Order, str], None] | None,
) -> None:
    if not config.auto_execution_enabled:
        return
    if order.status not in {OrderStatus.OUTREACH_SENT, OrderStatus.DISCOVERY, OrderStatus.DRAFT_READY}:
        return
    execution_dir = store.order_dir(order.order_id) / "execution"
    existed = (execution_dir / "checklist.md").exists()
    path = prepare_execution_workspace(store=store, order=order)
    if not existed:
        _safe_notify(
            sender,
            (
                "Рабочий пакет выполнения создан.\n\n"
                f"ID: {order.order_id}\n"
                f"Папка: {path.relative_to(store.order_dir(order.order_id))}\n"
                "Внутри: context.md, checklist.md, notes.md и стартовые артефакты результата."
            ),
        )
    _maybe_generate_execution_draft(
        config=config,
        store=store,
        order=order,
        sender=sender,
        execution_draft_client=execution_draft_client,
        send_delivery=send_delivery,
    )


def _maybe_generate_execution_draft(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    sender: Callable[..., None],
    execution_draft_client: ExecutionDraftClient | None,
    send_delivery: Callable[[Order, str], None] | None,
) -> None:
    if not config.auto_execution_draft_enabled or execution_draft_client is None:
        return
    order_dir = store.order_dir(order.order_id)
    generated_dir = order_dir / "execution" / "generated"
    if generated_dir.exists() and any(generated_dir.iterdir()):
        _maybe_finalize_delivery(
            store=store,
            order=order,
            sender=sender,
            config=config,
            send_delivery=send_delivery,
            quality_client=execution_draft_client,
        )
        return
    try:
        conversation_text = _read_optional_text(order_dir / "conversation.md")
        execution_context = _read_execution_context(order_dir / "execution")
        package = execution_draft_client.draft_execution_package(order, conversation_text, execution_context)
        written = write_execution_draft_package(store=store, order=order, package=package)
    except Exception as exc:
        _safe_notify(sender, f"AI-пакет результата по заказу {order.order_id} не создан: {type(exc).__name__}.")
        return
    _safe_notify(
        sender,
        (
            "AI-пакет результата подготовлен.\n\n"
            f"ID: {order.order_id}\n"
            f"Файлов: {len(written)}\n"
            "Результат лежит в execution/generated/, сообщение заказчику - в outbox/delivery_message.md."
        ),
    )
    _maybe_finalize_delivery(
        store=store,
        order=order,
        sender=sender,
        config=config,
        send_delivery=send_delivery,
        quality_client=execution_draft_client,
    )


def _maybe_finalize_delivery(
    *,
    store: OrderStore,
    order: Order,
    sender: Callable[..., None],
    config: Config,
    send_delivery: Callable[[Order, str], None] | None,
    quality_client: ExecutionDraftClient | None,
) -> None:
    if _delivery_sent_path(store, order).exists():
        return
    if not config.auto_delivery_enabled:
        _maybe_request_delivery_approval(store=store, order=order, sender=sender)
        return

    if config.auto_quality_enabled and not _run_delivery_quality_gate(
        config=config,
        store=store,
        order=order,
        sender=sender,
        quality_client=quality_client,
    ):
        return

    block_reason = _auto_delivery_block_reason(
        config=config,
        store=store,
        order=order,
        send_delivery=send_delivery,
    )
    if block_reason:
        _safe_notify(
            sender,
            (
                "Автосдача результата заблокирована.\n\n"
                f"ID: {order.order_id}\n"
                f"Причина: {block_reason}\n\n"
                "Результат оставлен на ручное подтверждение."
            ),
        )
        _maybe_request_delivery_approval(store=store, order=order, sender=sender)
        return

    delivery_text = _read_delivery_text(store, order)
    try:
        delivery_text = _append_payment_request_if_needed(store=store, order=order, config=config, text=delivery_text)
        delivery_payload = build_delivery_payload(
            store=store,
            order=order,
            message_text=delivery_text,
            public_base_url=config.delivery_public_base_url,
            public_dir=config.delivery_public_dir,
        )
        send_delivery(order, delivery_payload.message_text)
    except Exception as exc:
        _safe_notify(sender, f"Результат по заказу {order.order_id} не отправлен автоматически: {type(exc).__name__}.")
        _maybe_request_delivery_approval(store=store, order=order, sender=sender)
        return

    updated = store.update_status(order.order_id, OrderStatus.PAYMENT_REQUESTED)
    _write_delivery_sent_record(
        store=store,
        order=updated,
        text=delivery_payload.message_text,
        delivery_payload=delivery_payload,
    )
    channel_label = "email" if order.contact and order.contact.channel == "email" else "Freelancehunt"
    _safe_notify(
        sender,
        (
            f"Результат автоматически отправлен заказчику через {channel_label}.\n\n"
            f"ID: {updated.order_id}\n"
            "Статус: ожидаем оплату / подтверждение безопасной сделки."
        ),
    )


def _run_delivery_quality_gate(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    sender: Callable[..., None],
    quality_client: ExecutionDraftClient | None,
) -> bool:
    quality_dir = store.order_dir(order.order_id) / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    conversation_text = _read_optional_text(store.order_dir(order.order_id) / "conversation.md")

    for attempt in range(1, config.auto_quality_max_repairs + 2):
        package = read_execution_draft_package(store=store, order=order)
        local_report = check_generated_package(
            store.order_dir(order.order_id) / "execution" / "generated",
            delivery_message=package.delivery_message_ru,
            task_category=route_order_task(order).task_type.value,
        )
        ai_review: AIQualityReview | None = None
        ai_error: str | None = None
        execution_report = None
        if local_report.passed and config.execution_verify_enabled:
            verifier = DockerExecutionVerifier(
                python_image=config.execution_python_image,
                node_image=config.execution_node_image,
                timeout_seconds=config.execution_timeout_seconds,
                memory_mb=config.execution_memory_mb,
                cpus=config.execution_cpus,
                max_output_bytes=config.execution_max_output_bytes,
            )
            execution_report = verifier.verify(store.order_dir(order.order_id) / "execution" / "generated")
            _write_execution_verification(store=store, order=order, attempt=attempt, report=execution_report)
        execution_passed = execution_report is None or execution_report.status == VerificationStatus.PASSED
        if local_report.passed and execution_passed and quality_client is not None:
            try:
                ai_review = quality_client.review_execution_package(order, conversation_text, package)
            except Exception as exc:
                ai_error = type(exc).__name__
        elif quality_client is None:
            ai_error = "quality_client_unavailable"

        passed = local_report.passed and execution_passed and ai_review is not None and ai_review.passed
        report_data = {
            "attempt": attempt,
            "checked_at": format_moscow_time(),
            "passed": passed,
            "local": local_report.to_dict(),
            "execution_verification": execution_report.to_dict() if execution_report is not None else None,
            "ai": (
                {
                    "passed": ai_review.passed,
                    "issues": list(ai_review.issues),
                    "repair_instructions_ru": ai_review.repair_instructions_ru,
                }
                if ai_review is not None
                else {"passed": False, "issues": [ai_error or "AI-проверка не выполнена"], "repair_instructions_ru": ""}
            ),
        }
        _write_quality_json(quality_dir / f"attempt-{attempt:03d}.json", report_data)
        _write_quality_json(quality_dir / "latest.json", report_data)
        if passed:
            return True

        if execution_report is not None and execution_report.status in {
            VerificationStatus.RUNTIME_UNAVAILABLE,
            VerificationStatus.UNSUPPORTED,
        }:
            failed = store.update_status(order.order_id, OrderStatus.QUALITY_FAILED)
            _write_quality_json(
                quality_dir / "quality_failed.json",
                {"failed_at": format_moscow_time(), "attempts": attempt, "last_report": report_data},
            )
            _safe_notify(
                sender,
                f"Автопроверка выполнения заказа {failed.order_id} заблокирована: {execution_report.status.value}.",
            )
            return False

        if attempt > config.auto_quality_max_repairs:
            failed = store.update_status(order.order_id, OrderStatus.QUALITY_FAILED)
            _write_quality_json(
                quality_dir / "quality_failed.json",
                {
                    "failed_at": format_moscow_time(),
                    "attempts": attempt,
                    "last_report": report_data,
                },
            )
            _safe_notify(
                sender,
                (
                    "Автопроверка качества завершилась без успешного результата.\n\n"
                    f"ID: {failed.order_id}\n"
                    "Статус: quality_failed\n"
                    f"Попыток исправления: {config.auto_quality_max_repairs}\n"
                    "Файлы заказчику не отправлены."
                ),
            )
            return False

        instructions = [issue.message for issue in local_report.issues]
        if execution_report is not None:
            instructions.extend(issue.message for issue in execution_report.issues)
        if ai_review is not None:
            instructions.extend(ai_review.issues)
            if ai_review.repair_instructions_ru:
                instructions.append(ai_review.repair_instructions_ru)
        if ai_error:
            instructions.append(f"Повтори AI-проверку после исправления; предыдущая ошибка: {ai_error}.")
        try:
            if quality_client is None:
                raise RuntimeError("quality client unavailable")
            repaired = quality_client.repair_execution_package(
                order,
                conversation_text,
                package,
                "\n".join(dict.fromkeys(instructions)),
            )
            replace_execution_draft_package(store=store, order=order, package=repaired)
        except Exception as exc:
            report_data["repair_error"] = type(exc).__name__
            _write_quality_json(quality_dir / f"attempt-{attempt:03d}.json", report_data)
            _write_quality_json(quality_dir / "latest.json", report_data)

    return False


def _write_execution_verification(*, store: OrderStore, order: Order, attempt: int, report) -> None:
    directory = store.order_dir(order.order_id) / "execution" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    _write_quality_json(directory / f"attempt-{attempt:03d}.json", payload)
    _write_quality_json(directory / "latest.json", payload)
    stdout = "\n".join(command.stdout for command in report.commands if command.stdout)
    stderr = "\n".join(command.stderr for command in report.commands if command.stderr)
    (directory / f"stdout-{attempt:03d}.log").write_text(stdout, encoding="utf-8")
    (directory / f"stderr-{attempt:03d}.log").write_text(stderr, encoding="utf-8")


def _write_quality_json(path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _auto_delivery_block_reason(
    *,
    config: Config,
    store: OrderStore,
    order: Order,
    send_delivery: Callable[[Order, str], None] | None,
) -> str | None:
    order_dir = store.order_dir(order.order_id)
    delivery_message_path = order_dir / "outbox" / "delivery_message.md"
    generated_dir = order_dir / "execution" / "generated"
    allowed_statuses = {
        OrderStatus.OUTREACH_SENT,
        OrderStatus.DISCOVERY,
        OrderStatus.DRAFT_READY,
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
    }
    if order.risks:
        return "у заказа есть риск-флаги"
    if order.status not in allowed_statuses:
        return f"статус {order.status.value} не разрешен для автосдачи"
    if send_delivery is None:
        return "нет подключенного канала отправки результата"
    if _needs_external_payment_channel(order) and not _has_external_payment_channel(config):
        return "нет платежного канала для email-заказа"
    if _auto_delivery_count_today(store) >= config.auto_delivery_daily_limit:
        return "дневной лимит автосдачи исчерпан"
    if not delivery_message_path.exists():
        return "нет outbox/delivery_message.md"
    if not generated_dir.exists() or not any(path.is_file() for path in generated_dir.glob("*")):
        return "нет файлов результата в execution/generated/"

    delivery_text = _read_delivery_text(store, order).lower()
    blocked_terms = [
        "логин и пароль",
        "логин/пароль",
        "пароль от",
        "seed",
        "private key",
        "приватный ключ",
        "обойти лимит",
        "обход лимитов",
        "накрут",
        "фишинг",
        "вредонос",
        "мимо безопасной сделки",
        "вне безопасной сделки",
        "без безопасной сделки",
    ]
    for term in blocked_terms:
        if term in delivery_text:
            return f"опасный маркер: {term}"
    return None


def _append_payment_request_if_needed(*, store: OrderStore, order: Order, config: Config, text: str) -> str:
    if not _needs_external_payment_channel(order):
        return text
    amount_rub = order.price_rub or config.auto_max_price_rub
    if config.yookassa_shop_id and config.yookassa_secret_key:
        payment = YooKassaPaymentClient(
            shop_id=config.yookassa_shop_id,
            secret_key=config.yookassa_secret_key,
            return_url=config.payment_return_url,
        ).create_payment(
            order=order,
            amount_rub=amount_rub,
            description=f"Оплата заказа {order.order_id}: {order.category}",
        )
    else:
        payment = build_static_payment_request(
            order=order,
            amount_rub=amount_rub,
            instructions_ru=config.payment_instructions_ru,
        )
    write_payment_request(store=store, order=order, payment=payment)
    return text.rstrip() + "\n" + format_payment_block(payment) + "\n"


def _needs_external_payment_channel(order: Order) -> bool:
    return bool(order.contact and order.contact.channel == "email")


def _has_external_payment_channel(config: Config) -> bool:
    return bool(
        (config.yookassa_shop_id and config.yookassa_secret_key)
        or config.payment_instructions_ru.strip()
    )


def _auto_delivery_count_today(store: OrderStore) -> int:
    today_prefix = format_moscow_time().split(" ", 1)[0]
    count = 0
    for path in store.orders_dir.glob("*/outbox/delivery_message.sent.json"):
        try:
            if today_prefix in path.read_text(encoding="utf-8"):
                count += 1
        except OSError:
            continue
    return count


def _maybe_request_delivery_approval(
    *,
    store: OrderStore,
    order: Order,
    sender: Callable[..., None],
) -> None:
    order_dir = store.order_dir(order.order_id)
    marker_path = order_dir / "outbox" / "delivery_approval_requested.json"
    delivery_message_path = order_dir / "outbox" / "delivery_message.md"
    generated_dir = order_dir / "execution" / "generated"
    if marker_path.exists() or not delivery_message_path.exists() or not generated_dir.exists():
        return
    generated_files = sorted(path.relative_to(order_dir) for path in generated_dir.glob("*") if path.is_file())
    updated = replace(order, status=OrderStatus.AWAITING_DELIVERY_APPROVAL, updated_at=format_moscow_time())
    store.save_order(updated)
    marker_path.write_text(
        json.dumps(
            {
                "requested_at": format_moscow_time(),
                "generated_files": [str(path) for path in generated_files],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _safe_notify(
        sender,
        (
            "Результат готов к проверке.\n\n"
            f"ID: {updated.order_id}\n"
            f"Файлов: {len(generated_files)}\n"
            "Проверь execution/generated/ и outbox/delivery_message.md, затем нажми «Разрешить отправку»."
        ),
        reply_markup=build_order_keyboard(updated),
    )


def _read_execution_context(execution_dir) -> str:
    parts = []
    for name in ("context.md", "checklist.md", "notes.md"):
        text = _read_optional_text(execution_dir / name)
        if text:
            parts.append(f"# {name}\n\n{text}")
    return "\n\n".join(parts)


def _read_optional_text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _maybe_run_autopilot(
    *,
    config: Config,
    order: Order,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
    send_outreach: Callable[[Order, str], None] | None,
    email_health: EmailTransportHealth | None = None,
    raise_on_error: bool = False,
) -> Order:
    if config.auto_mode == "off" or not config.openai_api_key:
        return order

    client = autopilot_client or OpenAIResponsesClient(
        api_key=config.openai_api_key,
        model=config.openai_model,
        base_url=config.openai_base_url,
    )
    try:
        result = client.analyze_order(order)
        updated = run_order_autopilot(
            order=order,
            store=store,
            result=result,
            max_price_rub=config.auto_max_price_rub,
            mode=config.auto_mode,
        )
        updated = _maybe_auto_send_outreach(
            config=config,
            order=updated,
            store=store,
            sender=sender,
            send_outreach=send_outreach,
            email_health=email_health,
        )
    except Exception as exc:
        if raise_on_error:
            raise
        _safe_notify(sender, f"AI-черновик по заказу {order.order_id} не создан: {type(exc).__name__}")
        return order

    _safe_notify(sender, _autopilot_status_message(updated, config.auto_mode))
    return updated


def _maybe_auto_send_outreach(
    *,
    config: Config,
    order: Order,
    store: OrderStore,
    sender: Callable[..., None],
    send_outreach: Callable[[Order, str], None] | None,
    email_health: EmailTransportHealth | None = None,
) -> Order:
    if not config.auto_outreach_enabled or order.status != OrderStatus.DRAFT_READY:
        return order
    if _order_is_stale(order, max_age_hours=config.auto_outreach_max_age_hours):
        updated = store.update_status(order.order_id, OrderStatus.SKIPPED)
        _safe_notify(sender, f"Автоотклик по заказу {order.order_id} пропущен: проект устарел.")
        return updated
    if not order.contact or not order.contact.can_auto_send:
        updated = store.update_status(order.order_id, OrderStatus.CONTACT_UNAVAILABLE)
        _safe_notify(sender, f"Автоотклик по заказу {order.order_id} невозможен: контакт не опубликован.")
        return updated
    email_block_reason = _email_outreach_block_reason(order=order, email_health=email_health)
    if email_block_reason:
        if _write_outreach_channel_blocked(store=store, order=order, reason=email_block_reason):
            _safe_notify(sender, f"Автоотклик по заказу {order.order_id} отложен: {email_block_reason}.")
        return order
    if send_outreach is None:
        if order.contact.channel == "email":
            reason = "SMTP не настроен"
            if _write_outreach_channel_blocked(store=store, order=order, reason=reason):
                _safe_notify(sender, f"Автоотклик по заказу {order.order_id} отложен: {reason}.")
            return order
        return order
    if _auto_outreach_count_today(store) >= config.auto_outreach_daily_limit:
        _safe_notify(sender, f"Автоотклик по заказу {order.order_id} пропущен: дневной лимит исчерпан.")
        return order

    outreach_text = _read_outreach_text(store, order)
    try:
        send_outreach(order, outreach_text)
    except Exception as exc:
        updated = replace(
            order,
            status=_outreach_failure_status(exc),
            latest_approved_outreach=outreach_text,
            updated_at=format_moscow_time(),
        )
        store.save_order(updated)
        _write_outreach_send_failure(store=store, order=updated, exc=exc)
        _safe_notify(sender, f"Автоотклик по заказу {order.order_id} не отправлен: {type(exc).__name__}.")
        return updated

    _clear_outreach_channel_blocked(store=store, order=order)
    updated = replace(
        order,
        status=OrderStatus.OUTREACH_SENT,
        latest_approved_outreach=outreach_text,
        updated_at=format_moscow_time(),
    )
    store.save_order(updated)
    _safe_notify(
        sender,
        (
            f"Автоотклик отправлен через {updated.contact.channel}.\n\n"
            f"ID: {updated.order_id}\n"
            f"Проект: {updated.source_url}\n"
            f"Цена: {updated.price_rub} руб.\n"
            f"Срок: {updated.deadline_ru or 'не указан'}"
        ),
    )
    return updated


def _clear_outreach_channel_blocked(*, store: OrderStore, order: Order) -> None:
    path = store.order_dir(order.order_id) / "outbox" / "channel_blocked.json"
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _write_outreach_channel_blocked(*, store: OrderStore, order: Order, reason: str) -> bool:
    path = store.order_dir(order.order_id) / "outbox" / "channel_blocked.json"
    payload = {
        "checked_at": format_moscow_time(),
        "channel": order.contact.channel if order.contact else None,
        "reason": reason,
        "retry_status": order.status.value,
    }
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("reason") == reason:
                previous["checked_at"] = payload["checked_at"]
                path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return False
        except (OSError, json.JSONDecodeError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _email_outreach_block_reason(*, order: Order, email_health: EmailTransportHealth | None) -> str | None:
    if not order.contact or order.contact.channel != "email" or email_health is None:
        return None
    if not email_health.smtp_configured:
        return "SMTP не настроен"
    if not email_health.smtp_reachable:
        return f"SMTP недоступен: {email_health.smtp_error or 'connection failed'}"
    return None


def _auto_outreach_count_today(store: OrderStore) -> int:
    today_prefix = format_moscow_time().split(" ", 1)[0]
    return sum(
        1
        for order in store.list_orders()
        if order.status == OrderStatus.OUTREACH_SENT and order.updated_at.startswith(today_prefix)
    )


def _order_is_stale(order: Order, *, max_age_hours: int) -> bool:
    if max_age_hours <= 0:
        return False
    try:
        created_at = datetime.strptime(order.created_at, "%d.%m.%Y %H:%M МСК").replace(tzinfo=MOSCOW_TZ)
    except ValueError:
        return True
    return datetime.now(MOSCOW_TZ) - created_at > timedelta(hours=max_age_hours)


def _safe_notify(sender: Callable[..., None], text: str, **kwargs) -> None:
    try:
        sender(text, **kwargs)
    except Exception as exc:
        print(f"Telegram notification failed: {type(exc).__name__}")


def _autopilot_status_message(order: Order, mode: str) -> str:
    if order.status == OrderStatus.OUTREACH_SENT:
        return (
            "AI-агент уже отправил отклик.\n\n"
            f"ID: {order.order_id}\n"
            f"Статус: {order.status.value}\n"
            f"Цена: {order.price_rub or 'не указана'} руб.\n"
            f"Срок: {order.deadline_ru or 'не указан'}\n\n"
            "Дальше нужно ждать ответа заказчика в переписке Freelancehunt."
        )
    if mode == "autopilot" and order.status.value == "draft_ready":
        return (
            "AI-агент подготовил черновое выполнение.\n\n"
            f"ID: {order.order_id}\n"
            f"Статус: {order.status.value}\n"
            f"Цена: {order.price_rub or 'не указана'} руб.\n"
            f"Срок: {order.deadline_ru or 'не указан'}\n\n"
            "Файлы лежат в папке заказа: autopilot/, deliverables/, outbox/."
        )
    if mode == "autopilot" and order.status == OrderStatus.SKIPPED:
        reason = ", ".join(order.risks) if order.risks else "нет безопасной цены в разрешенном лимите"
        return (
            "AI-агент пропустил заказ по правилам автопилота.\n\n"
            f"ID: {order.order_id}\n"
            f"Причина: {reason}\n\n"
            "Ручное подтверждение не требуется."
        )
    return (
        "AI-агент подготовил черновики для проверки.\n\n"
        f"ID: {order.order_id}\n"
        f"Статус: {order.status.value}\n\n"
        "Файлы лежат в папке заказа: autopilot/, deliverables/, outbox/."
    )


def handle_order_callback(
    *,
    callback_data: str,
    store: OrderStore,
    answer: Callable[[str], None],
    send_outreach: Callable[[Order, str], None] | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
) -> Order | None:
    try:
        parsed = parse_callback_data(callback_data)
        order = store.load_order(parsed.order_id)
    except (ValueError, FileNotFoundError, KeyError):
        answer("Действие уже неактуально или недоступно.")
        return None

    if parsed.action.value == "approve_outreach" and order.status in {
        OrderStatus.AWAITING_RESPONSE_APPROVAL,
        OrderStatus.DRAFT_READY,
    }:
        return _approve_outreach(
            order=order,
            store=store,
            answer=answer,
            send_outreach=send_outreach,
        )

    if parsed.action == CallbackAction.ALLOW_SENDING and order.status == OrderStatus.AWAITING_DELIVERY_APPROVAL:
        return _approve_delivery(
            order=order,
            store=store,
            answer=answer,
            send_delivery=send_delivery,
        )

    next_status = resolve_transition(
        action=parsed.action,
        current_status=order.status,
        can_auto_send=bool(order.contact and order.contact.can_auto_send),
    )
    if next_status is None:
        answer("Действие уже неактуально или недоступно.")
        return None

    updated = store.update_status(order.order_id, next_status)
    answer("Готово.")
    return updated


def _approve_outreach(
    *,
    order: Order,
    store: OrderStore,
    answer: Callable[[str], None],
    send_outreach: Callable[[Order, str], None] | None,
) -> Order:
    outreach_text = _read_outreach_text(store, order)
    if order.contact and order.contact.can_auto_send and send_outreach is not None:
        try:
            send_outreach(order, outreach_text)
        except Exception as exc:
            updated = replace(
                order,
                status=_outreach_failure_status(exc),
                latest_approved_outreach=outreach_text,
                updated_at=format_moscow_time(),
            )
            store.save_order(updated)
            _write_outreach_send_failure(store=store, order=updated, exc=exc)
            answer(f"Отклик не отправлен: {type(exc).__name__}.")
            return updated
        updated = replace(
            order,
            status=OrderStatus.OUTREACH_SENT,
            latest_approved_outreach=outreach_text,
            updated_at=format_moscow_time(),
        )
        store.save_order(updated)
        answer(f"Отклик отправлен через {order.contact.channel}.")
        return updated

    updated = replace(
        order,
        status=OrderStatus.MANUAL_SEND_NEEDED,
        latest_approved_outreach=outreach_text,
        updated_at=format_moscow_time(),
    )
    store.save_order(updated)
    answer("Готово.")
    return updated


def _approve_delivery(
    *,
    order: Order,
    store: OrderStore,
    answer: Callable[[str], None],
    send_delivery: Callable[[Order, str], None] | None,
) -> Order:
    delivery_text = _read_delivery_text(store, order)
    quality_block = _delivery_quality_block_reason(store=store, order=order)
    if quality_block:
        answer(f"QA не пройдена: {quality_block}. Результат не отправлен.")
        return order
    if send_delivery is None:
        updated = store.update_status(order.order_id, OrderStatus.PAYMENT_REQUESTED)
        answer("Готово. Отправь результат вручную.")
        return updated
    try:
        delivery_payload = build_delivery_payload(store=store, order=order, message_text=delivery_text)
        send_delivery(order, delivery_payload.message_text)
    except Exception as exc:
        answer(f"Результат не отправлен: {type(exc).__name__}.")
        return order
    updated = store.update_status(order.order_id, OrderStatus.PAYMENT_REQUESTED)
    _write_delivery_sent_record(
        store=store,
        order=updated,
        text=delivery_payload.message_text,
        delivery_payload=delivery_payload,
    )
    answer("Результат отправлен заказчику.")
    return updated


def _read_delivery_text(store: OrderStore, order: Order) -> str:
    path = store.order_dir(order.order_id) / "outbox" / "delivery_message.md"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "Здравствуйте! Подготовил результат, прошу проверить."


def _write_delivery_sent_record(
    *,
    store: OrderStore,
    order: Order,
    text: str,
    delivery_payload: DeliveryPayload | None = None,
) -> None:
    order_dir = store.order_dir(order.order_id)
    outbox_dir = order_dir / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    sent_at = format_moscow_time()
    legacy_payload = {"sent_at": sent_at, "message": text}
    _delivery_sent_path(store, order).write_text(
        json.dumps(legacy_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = _write_delivery_package_manifest(store=store, order=order)
    receipt = {
        "status": "sent",
        "sent_at": sent_at,
        "order_id": order.order_id,
        "channel": _delivery_channel(order),
        "delivery_mode": delivery_payload.delivery_mode if delivery_payload else "manual_message",
        "attachment_supported": delivery_payload.attachment_supported if delivery_payload else False,
        "archive": delivery_payload.archive_path if delivery_payload else None,
        "public_url": delivery_payload.public_url if delivery_payload else None,
        "public_path": delivery_payload.public_path if delivery_payload else None,
        "instructions_ru": delivery_payload.instructions_ru if delivery_payload else None,
        "message": text,
        "generated_files": _generated_file_list(store=store, order=order),
        "quality": _delivery_quality_summary(store=store, order=order),
        "fallback": {
            "manifest": str(manifest_path.relative_to(order_dir)),
            "instruction": "Если канал площадки не поддерживает вложения, передайте заказчику файлы из локального пакета и сохраните внешний receipt.",
        },
    }
    _delivery_receipt_path(store, order).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _delivery_sent_path(store: OrderStore, order: Order):
    return store.order_dir(order.order_id) / "outbox" / "delivery_message.sent.json"


def _delivery_receipt_path(store: OrderStore, order: Order):
    return store.order_dir(order.order_id) / "outbox" / "delivery_receipt.json"


def _delivery_channel(order: Order) -> str:
    if order.contact and order.contact.channel:
        return order.contact.channel
    return "manual"


def _generated_file_list(*, store: OrderStore, order: Order) -> list[str]:
    order_dir = store.order_dir(order.order_id)
    generated_dir = order_dir / "execution" / "generated"
    if not generated_dir.exists():
        return []
    return [
        path.relative_to(order_dir).as_posix()
        for path in sorted(generated_dir.rglob("*"))
        if path.is_file()
    ]


def _latest_quality_payload(*, store: OrderStore, order: Order) -> dict | None:
    path = store.order_dir(order.order_id) / "quality" / "latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passed": False, "error": "invalid_quality_report"}


def _delivery_quality_summary(*, store: OrderStore, order: Order) -> dict:
    payload = _latest_quality_payload(store=store, order=order)
    if payload is None:
        return {"passed": None, "report": None}
    return {
        "passed": bool(payload.get("passed")),
        "report": "quality/latest.json",
    }


def _delivery_quality_block_reason(*, store: OrderStore, order: Order) -> str | None:
    payload = _latest_quality_payload(store=store, order=order)
    if payload is None or payload.get("passed") is True:
        return None
    issue_codes: list[str] = []
    for section in ("local", "execution_verification", "ai"):
        value = payload.get(section)
        if not isinstance(value, dict):
            continue
        for issue in value.get("issues", []) or []:
            if isinstance(issue, dict) and issue.get("code"):
                issue_codes.append(str(issue["code"]))
            elif isinstance(issue, str):
                issue_codes.append(issue)
    return ", ".join(dict.fromkeys(issue_codes)) or "quality/latest.json passed=false"


def _write_delivery_package_manifest(*, store: OrderStore, order: Order):
    order_dir = store.order_dir(order.order_id)
    outbox_dir = order_dir / "outbox"
    path = outbox_dir / "delivery_package_manifest.json"
    payload = {
        "created_at": format_moscow_time(),
        "order_id": order.order_id,
        "generated_files": _generated_file_list(store=store, order=order),
        "delivery_message": "outbox/delivery_message.md",
        "quality": _delivery_quality_summary(store=store, order=order),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (outbox_dir / "delivery_fallback.md").write_text(
        (
            "# Fallback отправки результата\n\n"
            "Если канал площадки не поддерживает вложения, передайте заказчику файлы из `execution/generated/` "
            "и текст из `outbox/delivery_message.md`, затем сохраните внешний receipt в папке заказа.\n"
        ),
        encoding="utf-8",
    )
    return path


def _read_outreach_text(store: OrderStore, order: Order) -> str:
    path = store.order_dir(order.order_id) / "autopilot" / "outreach.md"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return order.latest_approved_outreach or FIRST_OUTREACH_DRAFT


def poll_telegram_once(
    *,
    updates: list[dict],
    store: OrderStore,
    answer_callback: Callable[[str, str], None],
    send_outreach: Callable[[Order, str], None] | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
) -> int | None:
    next_offset: int | None = None
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1

        callback = update.get("callback_query") or {}
        callback_id = callback.get("id")
        callback_data = callback.get("data")
        if not callback_id or not callback_data:
            continue

        handle_order_callback(
            callback_data=callback_data,
            store=store,
            answer=lambda text, callback_id=callback_id: answer_callback(callback_id, text),
            send_outreach=send_outreach,
            send_delivery=send_delivery,
        )
    return next_offset


def poll_telegram_safely(
    *,
    bot_token: str,
    offset: int | None,
    timeout_seconds: int,
    store: OrderStore,
    get_updates_func: Callable[..., list[dict]] = get_updates,
    answer_callback: Callable[[str, str], None],
    send_outreach: Callable[[Order, str], None] | None = None,
    send_delivery: Callable[[Order, str], None] | None = None,
) -> int | None:
    try:
        updates = get_updates_func(bot_token, offset=offset, timeout_seconds=timeout_seconds)
    except Exception as exc:
        print(f"Telegram polling failed: {type(exc).__name__}")
        return offset
    return poll_telegram_once(
        updates=updates,
        store=store,
        answer_callback=answer_callback,
        send_outreach=send_outreach,
        send_delivery=send_delivery,
    )


def run_local_agent_loop(
    config: Config,
    *,
    interval_seconds: int = 300,
    poll_timeout_seconds: int = 20,
) -> None:
    store = OrderStore(config.orders_path)
    offset: int | None = None
    send_outreach = (
        (lambda order, text: _send_marketplace_outreach(config, order, text))
        if config.freelancehunt_api_token or (config.smtp_host and config.smtp_from)
        else None
    )
    send_delivery = (
        (lambda order, text: _send_marketplace_delivery(config, order, text))
        if config.freelancehunt_api_token or (config.smtp_host and config.smtp_from)
        else None
    )
    while True:
        run_local_agent_once(config, send_outreach=send_outreach, send_delivery=send_delivery)
        next_offset = poll_telegram_safely(
            bot_token=config.bot_token,
            offset=offset,
            timeout_seconds=poll_timeout_seconds,
            store=store,
            answer_callback=lambda callback_id, text: answer_callback_query(config.bot_token, callback_id, text),
            send_outreach=send_outreach,
            send_delivery=send_delivery,
        )
        if next_offset is not None:
            offset = next_offset
        sleep(interval_seconds)


def _send_marketplace_outreach(config: Config, order: Order, text: str) -> None:
    if not order.contact:
        raise RuntimeError("order has no contact")
    if order.contact.channel == "email":
        if not config.smtp_host or not config.smtp_from:
            raise RuntimeError("SMTP_HOST and SMTP_FROM are required")
        SMTPOutreachClient(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            from_email=config.smtp_from,
            use_ssl=config.smtp_use_ssl,
        ).send(order, text)
        return
    if order.contact.channel == "freelancehunt":
        if not config.freelancehunt_api_token:
            raise RuntimeError("FREELANCEHUNT_API_TOKEN is required")
        client = FreelancehuntClient(api_token=config.freelancehunt_api_token)
        client.add_bid(
            project_id=order.contact.value,
            bid=FreelancehuntBid(
                days=config.freelancehunt_bid_days,
                amount_rub=order.price_rub or config.auto_max_price_rub,
                comment=text,
                safe_type=config.freelancehunt_bid_safe_type,
            ),
        )
        return
    raise RuntimeError(f"unsupported contact channel: {order.contact.channel}")


def _send_marketplace_delivery(config: Config, order: Order, text: str) -> None:
    if not order.contact:
        raise RuntimeError("order has no contact")
    if order.contact.channel == "email":
        if not config.smtp_host or not config.smtp_from:
            raise RuntimeError("SMTP_HOST and SMTP_FROM are required")
        archive_path = config.orders_path / order.order_id / "outbox" / "delivery_package.zip"
        attachments = [archive_path] if archive_path.exists() else None
        SMTPOutreachClient(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            from_email=config.smtp_from,
            use_ssl=config.smtp_use_ssl,
        ).send(order, text, attachments=attachments)
        return
    if order.contact.channel != "freelancehunt":
        raise RuntimeError(f"unsupported contact channel: {order.contact.channel}")
    if not config.freelancehunt_api_token:
        raise RuntimeError("FREELANCEHUNT_API_TOKEN is required")

    client = FreelancehuntClient(api_token=config.freelancehunt_api_token)
    for thread in client.list_threads():
        if thread.project_id == order.contact.value:
            client.add_thread_message(thread_id=thread.thread_id, message_html=text)
            return
    raise RuntimeError("matching Freelancehunt thread not found")


def main() -> int:
    config = Config.from_env()
    if os.environ.get("LOCAL_AGENT_LOOP", "").lower() in {"1", "true", "yes"}:
        interval_seconds = int(os.environ.get("LOCAL_AGENT_INTERVAL_SECONDS", "300"))
        run_local_agent_loop(config, interval_seconds=interval_seconds)
        return 0

    summary = run_local_agent_once(config)
    print(
        "checked={checked} matched={matched} sent={sent} seeded={seeded} errors={errors}".format(
            checked=summary.checked,
            matched=summary.matched,
            sent=summary.sent,
            seeded=summary.seeded,
            errors=summary.errors,
        )
    )
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
