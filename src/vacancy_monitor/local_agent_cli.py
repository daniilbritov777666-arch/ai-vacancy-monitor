from __future__ import annotations

import os
from collections.abc import Callable
from time import sleep
from typing import Protocol

from vacancy_monitor.agent import handle_matched_post
from vacancy_monitor.autopilot import OpenAIResponsesClient, run_order_autopilot
from vacancy_monitor.cli import MonitorSummary, run_monitor
from vacancy_monitor.config import Config
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_models import Order, OrderStatus
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.sources import fetch_channel_posts, fetch_rss_posts as fetch_rss_feed_posts
from vacancy_monitor.telegram import answer_callback_query, get_updates, send_telegram_message
from vacancy_monitor.telegram_control import parse_callback_data, resolve_transition


class AutopilotClient(Protocol):
    def analyze_order(self, order: Order):
        ...


def run_local_agent_once(
    config: Config,
    *,
    fetch_posts: Callable[[str], list[Post]] = fetch_channel_posts,
    fetch_rss_posts: Callable[[str], list[Post]] | None = fetch_rss_feed_posts,
    send_message: Callable[..., None] | None = None,
    autopilot_client: AutopilotClient | None = None,
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
    )
    return summary


def _process_pending_autopilot_orders(
    *,
    config: Config,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
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
        )


def _maybe_run_autopilot(
    *,
    config: Config,
    order: Order,
    store: OrderStore,
    sender: Callable[..., None],
    autopilot_client: AutopilotClient | None,
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
    except Exception as exc:
        sender(f"AI-черновик по заказу {order.order_id} не создан: {exc}")
        return order

    sender(_autopilot_status_message(updated, config.auto_mode))
    return updated


def _autopilot_status_message(order: Order, mode: str) -> str:
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
) -> Order | None:
    try:
        parsed = parse_callback_data(callback_data)
        order = store.load_order(parsed.order_id)
    except (ValueError, FileNotFoundError, KeyError):
        answer("Действие уже неактуально или недоступно.")
        return None

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


def poll_telegram_once(
    *,
    updates: list[dict],
    store: OrderStore,
    answer_callback: Callable[[str, str], None],
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
    )


def run_local_agent_loop(
    config: Config,
    *,
    interval_seconds: int = 300,
    poll_timeout_seconds: int = 20,
) -> None:
    store = OrderStore(config.orders_path)
    offset: int | None = None
    while True:
        run_local_agent_once(config)
        next_offset = poll_telegram_safely(
            bot_token=config.bot_token,
            offset=offset,
            timeout_seconds=poll_timeout_seconds,
            store=store,
            answer_callback=lambda callback_id, text: answer_callback_query(config.bot_token, callback_id, text),
        )
        if next_offset is not None:
            offset = next_offset
        sleep(interval_seconds)


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
