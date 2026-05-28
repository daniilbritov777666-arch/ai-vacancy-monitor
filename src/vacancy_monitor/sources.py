from __future__ import annotations

from collections.abc import Iterable
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

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


def fetch_rss_posts(feed_url: str) -> list[Post]:
    response = requests.get(
        feed_url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 vacancy-monitor/0.1"},
    )
    response.raise_for_status()
    return parse_rss_xml(_rss_source_name(feed_url), response.text)


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


def parse_rss_xml(source: str, xml: str) -> list[Post]:
    root = ElementTree.fromstring(xml)
    posts: list[Post] = []

    for item in root.findall(".//item"):
        title = _xml_text(item, "title")
        link = _xml_text(item, "link")
        description = _html_to_text(_xml_text(item, "description"))
        guid = _xml_text(item, "guid") or link or title
        pub_date = _xml_text(item, "pubDate")
        published_at = _parse_pub_date(pub_date)

        if not title or not link:
            continue

        posts.append(
            Post(
                source=source,
                post_id=f"{source}:{guid}",
                url=link,
                text=f"{title}\n{description}".strip(),
                published_at=published_at,
            )
        )

    return posts


def newest_first(posts: Iterable[Post]) -> list[Post]:
    return sorted(posts, key=lambda post: post.post_id, reverse=True)


def _xml_text(item: ElementTree.Element, name: str) -> str:
    node = item.find(name)
    return "".join(node.itertext()).strip() if node is not None else ""


def _html_to_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _parse_pub_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def _rss_source_name(feed_url: str) -> str:
    return feed_url.replace("https://", "").replace("http://", "").strip("/")
