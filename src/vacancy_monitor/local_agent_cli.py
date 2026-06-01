from __future__ import annotations

from collections.abc import Callable

from vacancy_monitor.agent import handle_matched_post
from vacancy_monitor.cli import MonitorSummary, run_monitor
from vacancy_monitor.config import Config
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_models import Order
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.sources import fetch_channel_posts, fetch_rss_posts as fetch_rss_feed_posts
from vacancy_monitor.telegram import send_telegram_message
from vacancy_monitor.telegram_control import parse_callback_data, resolve_transition


def run_local_agent_once(
    config: Config,
    *,
    fetch_posts: Callable[[str], list[Post]] = fetch_channel_posts,
    fetch_rss_posts: Callable[[str], list[Post]] | None = fetch_rss_feed_posts,
    send_message: Callable[..., None] | None = None,
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
        handle_matched_post(
            post=post,
            result=result,
            store=store,
            send_approval=lambda text, reply_markup: sender(text, reply_markup=reply_markup),
        )

    return run_monitor(
        channels=config.channels,
        rss_feeds=config.rss_feeds,
        state_path=config.state_path,
        fetch_posts=fetch_posts,
        fetch_rss_posts=fetch_rss_posts,
        send_message=lambda text: sender(text),
        send_first_run=config.send_first_run,
        on_match=on_match,
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


def main() -> int:
    config = Config.from_env()
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
