from __future__ import annotations

import os
from dataclasses import replace
from collections.abc import Callable
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
from vacancy_monitor.execution import prepare_execution_workspace
from vacancy_monitor.freelancehunt import (
    FreelancehuntBid,
    FreelancehuntClient,
    FreelancehuntThread,
    FreelancehuntThreadMessage,
)
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_models import Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.sources import fetch_channel_posts, fetch_rss_posts as fetch_rss_feed_posts
from vacancy_monitor.telegram import answer_callback_query, get_updates, send_telegram_message
from vacancy_monitor.telegram_control import parse_callback_data, resolve_transition


class AutopilotClient(Protocol):
    def analyze_order(self, order: Order):
        ...


class ConversationReplyClient(Protocol):
    def draft_thread_reply(self, order: Order, messages: list[FreelancehuntThreadMessage]) -> str:
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


def run_local_agent_once(
    config: Config,
    *,
    fetch_posts: Callable[[str], list[Post]] = fetch_channel_posts,
    fetch_rss_posts: Callable[[str], list[Post]] | None = fetch_rss_feed_posts,
    send_message: Callable[..., None] | None = None,
    autopilot_client: AutopilotClient | None = None,
    send_outreach: Callable[[Order, str], None] | None = None,
    freelancehunt_client: FreelancehuntConversationClient | None = None,
    conversation_reply_client: ConversationReplyClient | None = None,
) -> MonitorSummary:
    store = OrderStore(config.orders_path)
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
        if config.freelancehunt_api_token
        else None
    )

    def on_match(post: Post, result: MatchResult) -> None:
        order = handle_matched_post(
            post=post,
            result=result,
            store=store,
            send_approval=lambda text, reply_markup: sender(text, reply_markup=reply_markup),
        )
        _maybe_run_autopilot(
            config=config,
            order=order,
            store=store,
            sender=sender,
            autopilot_client=autopilot_client,
            send_outreach=outreach_sender,
        )

    summary = run_monitor(
        channels=config.channels,
        rss_feeds=config.rss_feeds,
        state_path=config.state_path,
        fetch_posts=fetch_posts,
        fetch_rss_posts=fetch_rss_posts,
        send_message=lambda text: sender(text),
        send_first_run=config.send_first_run,
        on_match=on_match,
    )
    _process_pending_autopilot_orders(
        config=config,
        store=store,
        sender=sender,
        autopilot_client=autopilot_client,
        send_outreach=outreach_sender,
    )
    _process_pending_auto_outreach_orders(
        config=config,
        store=store,
        sender=sender,
        send_outreach=outreach_sender,
    )
    _sync_freelancehunt_conversations(
        config=config,
        store=store,
        sender=sender,
        freelancehunt_client=freelancehunt_client,
        conversation_reply_client=conversation_reply_client,
    )
    return summary


def _process_pending_autopilot_orders(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
    send_outreach: Callable[[Order, str], None] | None,
) -> None:
    if config.auto_mode == "off" or not config.openai_api_key:
        return
    for order in store.list_orders():
        if order.status != OrderStatus.AWAITING_RESPONSE_APPROVAL:
            continue
        if (store.order_dir(order.order_id) / "autopilot" / "analysis.json").exists():
            continue
        _maybe_run_autopilot(
            config=config,
            order=order,
            store=store,
            sender=sender,
            autopilot_client=autopilot_client,
            send_outreach=send_outreach,
        )


def _process_pending_auto_outreach_orders(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    send_outreach: Callable[[Order, str], None] | None,
) -> None:
    if not config.auto_outreach_enabled:
        return
    for order in store.list_orders():
        if order.status != OrderStatus.DRAFT_READY:
            continue
        _maybe_auto_send_outreach(
            config=config,
            order=order,
            store=store,
            sender=sender,
            send_outreach=send_outreach,
        )


def _sync_freelancehunt_conversations(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    freelancehunt_client: FreelancehuntConversationClient | None = None,
    conversation_reply_client: ConversationReplyClient | None = None,
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
        if term in combined_text:
            return f"опасный маркер: {term}"
    return None


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
) -> None:
    if not config.auto_execution_enabled:
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
                f"Папка: {path.relative_to(store.order_dir(order.order_id))}"
            ),
        )


def _maybe_run_autopilot(
    *,
    config: Config,
    order: Order,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
    send_outreach: Callable[[Order, str], None] | None,
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
        )
    except Exception as exc:
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
) -> Order:
    if not config.auto_outreach_enabled or order.status != OrderStatus.DRAFT_READY:
        return order
    if order.risks:
        return order
    if send_outreach is None or not (order.contact and order.contact.can_auto_send):
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
            status=OrderStatus.SEND_FAILED,
            latest_approved_outreach=outreach_text,
            updated_at=format_moscow_time(),
        )
        store.save_order(updated)
        _safe_notify(sender, f"Автоотклик по заказу {order.order_id} не отправлен: {type(exc).__name__}.")
        return updated

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
            "Автоотклик отправлен на Freelancehunt.\n\n"
            f"ID: {updated.order_id}\n"
            f"Проект: {updated.source_url}\n"
            f"Цена: {updated.price_rub} руб.\n"
            f"Срок: {updated.deadline_ru or 'не указан'}"
        ),
    )
    return updated


def _auto_outreach_count_today(store: OrderStore) -> int:
    today_prefix = format_moscow_time().split(" ", 1)[0]
    return sum(
        1
        for order in store.list_orders()
        if order.status == OrderStatus.OUTREACH_SENT and order.updated_at.startswith(today_prefix)
    )


def _safe_notify(sender: Callable[..., None], text: str) -> None:
    try:
        sender(text)
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
                status=OrderStatus.SEND_FAILED,
                latest_approved_outreach=outreach_text,
                updated_at=format_moscow_time(),
            )
            store.save_order(updated)
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
        if config.freelancehunt_api_token
        else None
    )
    while True:
        run_local_agent_once(config, send_outreach=send_outreach)
        next_offset = poll_telegram_safely(
            bot_token=config.bot_token,
            offset=offset,
            timeout_seconds=poll_timeout_seconds,
            store=store,
            answer_callback=lambda callback_id, text: answer_callback_query(config.bot_token, callback_id, text),
            send_outreach=send_outreach,
        )
        if next_offset is not None:
            offset = next_offset
        sleep(interval_seconds)


def _send_marketplace_outreach(config: Config, order: Order, text: str) -> None:
    if not order.contact:
        raise RuntimeError("order has no contact")
    if order.contact.channel != "freelancehunt":
        raise RuntimeError(f"unsupported contact channel: {order.contact.channel}")
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
