from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from vacancy_monitor.models import Post


DEFAULT_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 vacancy-monitor/0.1"
MOSCOW = ZoneInfo("Europe/Moscow")

PUBLIC_SOURCE_URLS = {
    "freelance_ru": "https://freelance.ru/task",
    "pchel": "https://pchel.net/jobs/",
    "kwork": "https://kwork.ru/projects",
    "workzilla": "https://work-zilla.com/tasks",
}


@dataclass(frozen=True)
class PublicSourceHealth:
    source: str
    url: str
    checked_at: str
    status: str
    posts: int = 0
    error: str | None = None


class SourceContractError(RuntimeError):
    """Raised when a public source no longer matches its expected HTML contract."""


def fetch_public_project_posts(source_name: str) -> list[Post]:
    if source_name not in {"freelance_ru", "pchel"}:
        raise ValueError(f"Unsupported public project source: {source_name}")
    html = _fetch_html(source_name)
    fetched_at = datetime.now(tz=MOSCOW)
    if source_name == "freelance_ru":
        return parse_freelance_ru(html, fetched_at)
    return parse_pchel(html, fetched_at)


def probe_public_source(source_name: str) -> PublicSourceHealth:
    if source_name not in PUBLIC_SOURCE_URLS:
        raise ValueError(f"Unknown public source: {source_name}")
    checked_at = datetime.now(tz=MOSCOW).isoformat()
    try:
        html = _fetch_html(source_name)
        if source_name == "kwork":
            status = "client_rendered" if "<wants-view" in html else "contract_changed"
            posts = 0
        elif source_name == "workzilla":
            status = "examples_only" if "Примеры заданий" in html else "contract_changed"
            posts = 0
        elif source_name == "freelance_ru":
            posts = len(parse_freelance_ru(html, datetime.now(tz=MOSCOW)))
            status = "available"
        else:
            posts = len(parse_pchel(html, datetime.now(tz=MOSCOW)))
            status = "available"
        return PublicSourceHealth(source_name, PUBLIC_SOURCE_URLS[source_name], checked_at, status, posts)
    except Exception as exc:
        return PublicSourceHealth(
            source_name,
            PUBLIC_SOURCE_URLS[source_name],
            checked_at,
            "error",
            error=f"{type(exc).__name__}: {exc}",
        )


def _fetch_html(source_name: str) -> str:
    response = requests.get(
        PUBLIC_SOURCE_URLS[source_name],
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def write_public_source_health_report(path: Path, records: list[PublicSourceHealth]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": datetime.now(tz=MOSCOW).isoformat(),
        "sources": [asdict(record) for record in records],
    }
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def parse_freelance_ru(html: str, fetched_at: datetime) -> list[Post]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.task-card")
    if not cards:
        raise SourceContractError("Freelance.ru task cards were not found")

    posts: list[Post] = []
    for card in cards:
        link = card.select_one(".task-card__title-link")
        if link is None:
            continue
        href = link.get("href", "")
        match = re.search(r"/task/view/(\d+)", href)
        if not match:
            continue

        title = link.get_text(" ", strip=True)
        description = _text(card.select_one(".task-card__desc"))
        chips = [item.get_text(" ", strip=True) for item in card.select(".task-card__chips *")]
        budget = _text(card.select_one(".task-card__budget"))
        text = _join_parts(title, description, " ".join(dict.fromkeys(chips)), budget)

        published_at = None
        date_node = card.select_one(".task-card__foot-item[title]")
        if date_node is not None:
            raw_date = date_node.get("title", "").strip()
            try:
                published_at = datetime.strptime(raw_date, "%d.%m.%Y %H:%M").replace(
                    tzinfo=fetched_at.tzinfo
                )
            except ValueError:
                pass

        task_id = match.group(1)
        posts.append(
            Post(
                source="freelance.ru",
                post_id=f"freelance_ru:{task_id}",
                url=urljoin("https://freelance.ru", href),
                text=text,
                published_at=published_at.isoformat() if published_at else None,
            )
        )
    return posts


def parse_pchel(html: str, fetched_at: datetime) -> list[Post]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".project-block2")
    if not cards:
        raise SourceContractError("Pchel.net project cards were not found")

    posts: list[Post] = []
    for card in cards:
        link = card.select_one(".project-title a")
        if link is None:
            continue
        href = link.get("href", "")
        project_input = card.select_one('input[name="project_id"]')
        project_id = project_input.get("value", "").strip() if project_input else ""
        if not project_id:
            match = re.search(r"-(\d+)/?$", href)
            project_id = match.group(1) if match else ""
        if not project_id:
            continue

        title = link.get_text(" ", strip=True)
        description = _text(card.select_one(".project-text"))
        tags = _text(card.select_one(".project-tags"))
        budget = _text(card.select_one(".project-athor .price"))
        text = _join_parts(title, description, tags, budget)

        published_at = None
        raw_date = _text(card.select_one(".date")).lower()
        if "сегодня" in raw_date:
            published_at = fetched_at
        elif "вчера" in raw_date:
            published_at = fetched_at - timedelta(days=1)

        posts.append(
            Post(
                source="pchel.net",
                post_id=f"pchel:{project_id}",
                url=urljoin("https://pchel.net", href),
                text=text,
                published_at=published_at.isoformat() if published_at else None,
            )
        )
    return posts


def _text(node: object | None) -> str:
    if node is None:
        return ""
    return node.get_text(" ", strip=True)  # type: ignore[union-attr]


def _join_parts(*parts: str) -> str:
    return "\n".join(part for part in parts if part)
