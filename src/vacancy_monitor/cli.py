from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vacancy_monitor.config import Config
from vacancy_monitor.filtering import evaluate_post, format_match_message
from vacancy_monitor.models import Post
from vacancy_monitor.sources import fetch_channel_posts
from vacancy_monitor.state import SeenState
from vacancy_monitor.telegram import send_telegram_message


@dataclass(frozen=True)
class MonitorSummary:
    checked: int
    matched: int
    sent: int
    seeded: int
    errors: int


def run_monitor(
    *,
    channels: list[str],
    state_path: Path,
    fetch_posts: Callable[[str], list[Post]],
    send_message: Callable[[str], None],
    send_first_run: bool,
) -> MonitorSummary:
    state = SeenState.load(state_path)
    first_run = not state_path.exists() and not state.seen_ids

    checked = 0
    matched = 0
    sent = 0
    seeded = 0
    errors = 0

    for channel in channels:
        try:
            posts = fetch_posts(channel)
        except Exception as exc:
            errors += 1
            print(f"Failed to fetch {channel}: {exc}")
            continue

        for post in reversed(posts):
            if state.contains(post.post_id):
                continue

            checked += 1
            result = evaluate_post(post)
            state.add(post.post_id)

            if first_run and not send_first_run:
                seeded += 1
                continue

            if not result.accepted:
                continue

            matched += 1
            message = format_match_message(post, result)
            send_message(message)
            sent += 1

    state.save(state_path)
    return MonitorSummary(checked=checked, matched=matched, sent=sent, seeded=seeded, errors=errors)


def main() -> int:
    config = Config.from_env()
    summary = run_monitor(
        channels=config.channels,
        state_path=config.state_path,
        fetch_posts=fetch_channel_posts,
        send_message=lambda text: send_telegram_message(config.bot_token, config.chat_id, text),
        send_first_run=config.send_first_run,
    )
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
