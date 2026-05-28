from __future__ import annotations

from collections.abc import Iterable

import requests
from bs4 import BeautifulSoup

from vacancy_monitor.models import Post


DEFAULT_TIMEOUT_SECONDS = 20


def fetch_channel_posts(channel: str) -> list[Post]:
    url = f"https://t.me/s/{channel.lstrip('@')}"
    response = requests.get(
        url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 vacancy-monitor/0.1"},
    )
    response.raise_for_status()
    return parse_telegram_html(channel.lstrip("@"), response.text)


def parse_telegram_html(source: str, html: str) -> list[Post]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[Post] = []

    for message in soup.select(".tgme_widget_message"):
        post_id = message.get("data-post")
        text_node = message.select_one(".tgme_widget_message_text")
        if not post_id or text_node is None:
            continue

        date_link = message.select_one(".tgme_widget_message_date")
        time_node = message.select_one("time")
        url = date_link.get("href") if date_link else f"https://t.me/{post_id}"
        published_at = time_node.get("datetime") if time_node else None
        text = text_node.get_text("\n", strip=True)

        posts.append(
            Post(
                source=source,
                post_id=post_id,
                url=url or f"https://t.me/{post_id}",
                text=text,
                published_at=published_at,
            )
        )

    return posts


def newest_first(posts: Iterable[Post]) -> list[Post]:
    return sorted(posts, key=lambda post: post.post_id, reverse=True)
