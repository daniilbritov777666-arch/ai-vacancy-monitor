from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any

import requests

from vacancy_monitor.models import Post


API_BASE_URL = "https://api.freelancehunt.com/v2"


class FreelancehuntBidPreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class FreelancehuntBid:
    days: int
    amount: int
    comment: str
    safe_type: str = "employer"
    currency: str = "RUB"
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


@dataclass(frozen=True)
class FreelancehuntMyBid:
    bid_id: str
    project_id: str | None
    status: str | None
    is_winner: bool
    project_status: str | None
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

    def get_profile(self) -> dict:
        response = self.session.get(
            f"{self.base_url}/my/profile",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_project(self, project_id: str) -> dict:
        response = self.session.get(
            f"{self.base_url}/projects/{project_id}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_open_projects(self, *, page: int = 1, skill_ids: list[int] | None = None) -> list[dict]:
        filters = ""
        if skill_ids:
            filters = f"filter[skill_id]={','.join(str(skill_id) for skill_id in skill_ids)}&"
        response = self.session.get(
            f"{self.base_url}/projects?{filters}page[number]={max(1, page)}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return _data_list(response.json())

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
                "budget": {"amount": bid.amount, "currency": bid.currency},
                "comment": bid.comment,
                "is_hidden": bid.is_hidden,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_my_bids(self) -> list[FreelancehuntMyBid]:
        response = self.session.get(
            f"{self.base_url}/my/bids",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return [_my_bid_from_api(item) for item in _data_list(response.json())]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Accept-Language": "ru",
            "Content-Type": "application/json",
        }


def build_bid_preflight(*, profile: dict, project: dict) -> dict[str, Any]:
    profile_data = profile.get("data") if isinstance(profile, dict) else {}
    project_data = project.get("data") if isinstance(project, dict) else {}
    profile_data = profile_data if isinstance(profile_data, dict) else {}
    project_data = project_data if isinstance(project_data, dict) else {}
    profile_attributes = profile_data.get("attributes")
    project_attributes = project_data.get("attributes")
    profile_attributes = profile_attributes if isinstance(profile_attributes, dict) else {}
    project_attributes = project_attributes if isinstance(project_attributes, dict) else {}
    verification = profile_attributes.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    status = project_attributes.get("status")
    status = status if isinstance(status, dict) else {}

    blockers: list[str] = []
    if status.get("id") != 11:
        blockers.append("project_not_open_for_proposals")
    if project_attributes.get("freelancer"):
        blockers.append("project_has_contractor")
    project_safe_type = project_attributes.get("safe_type")
    if project_safe_type == "employer_cashless":
        blockers.append("business_safe_not_supported_by_api")
    elif project_safe_type not in {"employer", "developer", "split"}:
        blockers.append("unsupported_project_safe_type")

    warning_fields = {
        "identity": "profile_identity_not_verified",
        "birth_date": "profile_birth_date_not_verified",
        "phone": "profile_phone_not_verified",
        "email": "profile_email_not_verified",
    }
    warnings = [message for field, message in warning_fields.items() if verification.get(field) is False]
    return {
        "eligible": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "profile": {
            "id": str(profile_data.get("id") or ""),
            "type": profile_data.get("type"),
            "login": profile_attributes.get("login"),
            "is_plus_active": bool(profile_attributes.get("is_plus_active")),
            "status": status_value(profile_attributes.get("status")),
            "verification": {field: verification.get(field) for field in warning_fields},
        },
        "project": {
            "id": str(project_data.get("id") or ""),
            "status_id": status.get("id"),
            "status_name": status.get("name"),
            "safe_type": project_attributes.get("safe_type"),
            "budget": _safe_budget(project_attributes.get("budget")),
            "expired_at": project_attributes.get("expired_at"),
            "has_contractor": bool(project_attributes.get("freelancer")),
        },
    }


def fetch_freelancehunt_api_posts(
    api_token: str,
    pages: int = 1,
    skill_ids: list[int] | None = None,
    client: FreelancehuntClient | None = None,
) -> list[Post]:
    api = client or FreelancehuntClient(api_token=api_token)
    posts: list[Post] = []
    for page in range(1, min(5, max(1, pages)) + 1):
        for item in api.list_open_projects(page=page, skill_ids=skill_ids):
            post = _open_project_post(item)
            if post is not None:
                posts.append(post)
    return posts


def _open_project_post(item: dict) -> Post | None:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    status = attributes.get("status") if isinstance(attributes.get("status"), dict) else {}
    if status.get("id") != 11 or attributes.get("freelancer") or attributes.get("is_remote_job"):
        return None
    safe_type = attributes.get("safe_type")
    if safe_type not in {"employer", "developer", "split"}:
        return None
    budget = attributes.get("budget") if isinstance(attributes.get("budget"), dict) else None
    if budget and budget.get("currency") not in {"UAH", "RUB"}:
        return None
    project_id = str(item.get("id") or "")
    name = attributes.get("name")
    if not project_id or not isinstance(name, str) or not name.strip():
        return None
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    self_link = links.get("self")
    if isinstance(self_link, dict):
        url = self_link.get("web") or self_link.get("api")
    else:
        url = self_link
    url = url or f"{API_BASE_URL}/projects/{project_id}"
    parts = [name.strip(), str(attributes.get("description") or "").strip()]
    if budget:
        parts.append(f"Бюджет: {budget.get('amount')} {budget.get('currency')}")
    parts.append(f"Тип сделки: {safe_type}")
    return Post(
        source="freelancehunt_api",
        post_id=f"freelancehunt_api:{project_id}",
        url=str(url),
        text="\n".join(part for part in parts if part),
        published_at=attributes.get("published_at") if isinstance(attributes.get("published_at"), str) else None,
    )


def status_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"id": value.get("id"), "name": value.get("name")}


def _safe_budget(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"amount": value.get("amount"), "currency": value.get("currency")}


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


def _my_bid_from_api(item: dict) -> FreelancehuntMyBid:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    project = attributes.get("project") if isinstance(attributes.get("project"), dict) else {}
    project_status = project.get("status")
    if isinstance(project_status, dict):
        project_status = project_status.get("name") or project_status.get("slug") or project_status.get("id")
    return FreelancehuntMyBid(
        bid_id=str(item.get("id") or attributes.get("id") or ""),
        project_id=_extract_project_id(item),
        status=_first_str(attributes, "status", "state") or _first_str(item, "status", "state"),
        is_winner=bool(attributes.get("is_winner")),
        project_status=str(project_status) if project_status is not None else None,
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
