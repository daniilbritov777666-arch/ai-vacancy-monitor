from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from vacancy_monitor.models import Post

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class OrderStatus(StrEnum):
    NEW = "new"
    AWAITING_RESPONSE_APPROVAL = "awaiting_response_approval"
    OUTREACH_SENT = "outreach_sent"
    MANUAL_SEND_NEEDED = "manual_send_needed"
    SEND_FAILED = "send_failed"
    DISCOVERY = "discovery"
    AWAITING_TERMS_APPROVAL = "awaiting_terms_approval"
    DRAFT_READY = "draft_ready"
    AWAITING_DELIVERY_APPROVAL = "awaiting_delivery_approval"
    PAYMENT_REQUESTED = "payment_requested"
    QUALITY_FAILED = "quality_failed"
    SKIPPED = "skipped"
    CLOSED = "closed"


@dataclass(frozen=True)
class CustomerContact:
    channel: str
    value: str
    can_auto_send: bool = False


@dataclass(frozen=True)
class Order:
    order_id: str
    source: str
    source_url: str
    original_post_id: str
    original_text: str
    category: str
    status: OrderStatus
    created_at: str
    updated_at: str
    contact: CustomerContact | None = None
    latest_approved_outreach: str | None = None
    price_rub: int | None = None
    deadline_ru: str | None = None
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        contact_data = data.get("contact")
        contact = CustomerContact(**contact_data) if contact_data else None
        return cls(
            order_id=data["order_id"],
            source=data["source"],
            source_url=data["source_url"],
            original_post_id=data["original_post_id"],
            original_text=data["original_text"],
            category=data["category"],
            status=OrderStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            contact=contact,
            latest_approved_outreach=data.get("latest_approved_outreach"),
            price_rub=data.get("price_rub"),
            deadline_ru=data.get("deadline_ru"),
            risks=list(data.get("risks", [])),
        )


def format_moscow_time(value: datetime | None = None) -> str:
    current = value or datetime.now(tz=UTC)
    return current.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")


def build_order_id(post: Post) -> str:
    published = _parse_post_datetime(post.published_at)
    date_prefix = published.astimezone(MOSCOW_TZ).strftime("%Y%m%d")
    digest = hashlib.sha1(post.post_id.encode("utf-8")).hexdigest()[:10]
    source_slug = re.sub(r"[^a-zA-Z0-9]+", "-", post.source).strip("-").lower() or "source"
    return f"{date_prefix}-{source_slug}-{digest}"


def make_order_from_post(post: Post, *, category: str, risks: list[str] | None = None) -> Order:
    now_ru = format_moscow_time()
    return Order(
        order_id=build_order_id(post),
        source=post.source,
        source_url=post.url,
        original_post_id=post.post_id,
        original_text=post.text,
        category=category,
        status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        created_at=now_ru,
        updated_at=now_ru,
        contact=_contact_from_post(post),
        risks=risks or [],
    )


def _parse_post_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _contact_from_post(post: Post) -> CustomerContact | None:
    project_id = _freelancehunt_project_id(post.url) or _freelancehunt_project_id(post.post_id)
    if project_id:
        return CustomerContact(channel="freelancehunt", value=project_id, can_auto_send=True)
    return None


def _freelancehunt_project_id(value: str) -> str | None:
    if "freelancehunt.com" not in value:
        return None
    match = re.search(r"/project/[^/]+/(\d+)(?:\\.html)?", value)
    return match.group(1) if match else None
