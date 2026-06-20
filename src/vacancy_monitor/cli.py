from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vacancy_monitor.config import Config
from vacancy_monitor.filtering import evaluate_post, format_match_message
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.public_sources import fetch_public_project_posts
from vacancy_monitor.sources import fetch_channel_posts, fetch_rss_posts as fetch_rss_feed_posts
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
    rss_feeds: list[str] | None = None,
    public_project_sources: list[str] | None = None,
    state_path: Path,
    fetch_posts: Callable[[str], list[Post]],
    fetch_rss_posts: Callable[[str], list[Post]] | None = None,
    fetch_public_posts: Callable[[str], list[Post]] | None = None,
    send_message: Callable[[str], None],
    send_first_run: bool,
    on_match: Callable[[Post, MatchResult], None] | None = None,
) -> MonitorSummary:
    state = SeenState.load(state_path)
    first_run = not state_path.exists() and not state.seen_ids

    checked = 0
    matched = 0
    sent = 0
    seeded = 0
    errors = 0

    sources = [(channel, fetch_posts) for channel in channels]
    if rss_feeds and fetch_rss_posts:
        sources.extend((feed, fetch_rss_posts) for feed in rss_feeds)
    if public_project_sources and fetch_public_posts:
        sources.extend((source, fetch_public_posts) for source in public_project_sources)

    for source, fetcher in sources:
        try:
            posts = fetcher(source)
        except Exception as exc:
            errors += 1
            print(f"Failed to fetch {source}: {exc}")
            continue

        for post in reversed(posts):
            if state.contains(post.post_id):
                continue

            checked += 1
            result = evaluate_post(post)

            if first_run and not send_first_run:
                state.add(post.post_id)
                seeded += 1
                continue

            if not result.accepted:
                state.add(post.post_id)
                continue

            matched += 1
            try:
                if on_match is not None:
                    on_match(post, result)
                else:
                    message = format_match_message(post, result)
                    send_message(message)
            except Exception as exc:
                errors += 1
                print(f"Failed to handle matched post {post.url}: {type(exc).__name__}")
                state.add(post.post_id)
                continue
            state.add(post.post_id)
            sent += 1

    state.save(state_path)
    return MonitorSummary(checked=checked, matched=matched, sent=sent, seeded=seeded, errors=errors)


def main() -> int:
    config = Config.from_env()
    summary = run_monitor(
        channels=config.channels,
        rss_feeds=config.rss_feeds,
        public_project_sources=config.public_project_sources,
        state_path=config.state_path,
        fetch_posts=fetch_channel_posts,
        fetch_rss_posts=fetch_rss_feed_posts,
        fetch_public_posts=fetch_public_project_posts,
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
