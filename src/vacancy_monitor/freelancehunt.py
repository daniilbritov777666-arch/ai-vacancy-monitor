from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any

import requests


API_BASE_URL = "https://api.freelancehunt.com/v2"


@dataclass(frozen=True)
class FreelancehuntBid:
    days: int
    amount_rub: int
    comment: str
    safe_type: str = "employer"
    is_hidden: bool = False


@dataclass(frozen=True)
class FreelancehuntThread:
    thread_id: str
    project_id: str | None
    subject: str | None
    is_unread: bool
    updated_at: str | None
    raw: dict


@dataclass(frozen=True)
class FreelancehuntThreadMessage:
    message_id: str
    text: str
    created_at: str | None
    author_id: str | None
    author_type: str | None
    is_own: bool
    raw: dict


class FreelancehuntClient:
    def __init__(self, *, api_token: str, session: Any = requests, base_url: str = API_BASE_URL):
        self.api_token = api_token
        self.session = session
        self.base_url = base_url.rstrip("/")

    def list_threads(self) -> list[FreelancehuntThread]:
        response = self.session.get(
            f"{self.base_url}/threads",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return [_thread_from_api(item) for item in _data_list(payload)]

    def get_thread_messages(self, thread_id: str) -> list[FreelancehuntThreadMessage]:
        response = self.session.get(
            f"{self.base_url}/threads/{thread_id}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return [_message_from_api(item) for item in _extract_messages(payload)]

    def add_thread_message(self, *, thread_id: str, message_html: str) -> dict:
        response = self.session.post(
            f"{self.base_url}/threads/{thread_id}",
            headers=self._headers(),
            json={"message_html": message_html},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def mark_thread_read(self, thread_id: str) -> dict:
        response = self.session.post(
            f"{self.base_url}/threads/{thread_id}/mark-read",
            headers=self._headers(),
            json={},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def add_bid(self, *, project_id: str, bid: FreelancehuntBid) -> dict:
        response = self.session.post(
            f"{self.base_url}/projects/{project_id}/bids",
            headers=self._headers(),
            json={
                "days": bid.days,
                "safe_type": bid.safe_type,
                "budget": {"amount": bid.amount_rub, "currency": "RUB"},
                "comment": bid.comment,
                "is_hidden": bid.is_hidden,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_project_workspaces(self) -> list[dict]:
        response = self.session.get(
            f"{self.base_url}/my/workspaces/projects",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return _data_list(response.json())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Accept-Language": "ru",
            "Content-Type": "application/json",
        }


def _data_list(payload: Any) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _thread_from_api(item: dict) -> FreelancehuntThread:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    return FreelancehuntThread(
        thread_id=str(item.get("id") or attributes.get("id") or ""),
        project_id=_extract_project_id(item),
        subject=_first_str(attributes, "subject", "title", "name"),
        is_unread=not bool(attributes.get("is_read", True)),
        updated_at=_first_str(attributes, "updated_at", "last_message_at", "created_at"),
        raw=item,
    )


def _message_from_api(item: dict) -> FreelancehuntThreadMessage:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    author = _nested_dict(item, "relationships", "author", "data") or _nested_dict(attributes, "author") or {}
    text = _first_str(attributes, "message_html", "message", "text", "body") or _first_str(item, "message_html", "text") or ""
    return FreelancehuntThreadMessage(
        message_id=str(item.get("id") or attributes.get("id") or ""),
        text=_html_to_text(text),
        created_at=_first_str(attributes, "created_at", "date", "updated_at"),
        author_id=str(author.get("id")) if author.get("id") is not None else None,
        author_type=str(author.get("type")) if author.get("type") is not None else None,
        is_own=bool(attributes.get("is_own") or attributes.get("is_my")),
        raw=item,
    )


def _extract_messages(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        attributes = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        for source in (
            attributes.get("messages"),
            data.get("messages"),
            _nested_dict(data, "relationships", "messages", "data"),
            payload.get("included"),
        ):
            if isinstance(source, list):
                messages = [
                    item
                    for item in source
                    if isinstance(item, dict)
                    and (item.get("type") in {None, "message", "messages", "thread-message"} or "message" in item)
                ]
                if messages:
                    return messages
        return [data] if _first_str(attributes, "message_html", "message", "text", "body") else []
    return []


def _extract_project_id(item: dict) -> str | None:
    for path in (
        ("relationships", "project", "data", "id"),
        ("relationships", "workspace", "data", "id"),
        ("attributes", "project_id"),
        ("attributes", "project", "id"),
        ("project_id",),
    ):
        value = _nested_value(item, *path)
        if value:
            return str(value)

    text = repr(item)
    match = re.search(r"freelancehunt\.com/project/[^/]+/(\d+)(?:\.html)?", text)
    return match.group(1) if match else None


def _nested_dict(data: dict, *keys: str) -> dict:
    value = _nested_value(data, *keys)
    return value if isinstance(value, dict) else {}


def _nested_value(data: dict, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_str(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    text = unescape("".join(parser.parts) if parser.parts else value)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
