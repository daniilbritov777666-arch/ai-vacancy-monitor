from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from vacancy_monitor.conversation import find_order_for_thread
from vacancy_monitor.freelancehunt import FreelancehuntMyBid, FreelancehuntThread
from vacancy_monitor.order_models import MOSCOW_TZ, format_moscow_time
from vacancy_monitor.order_store import OrderStore


class FreelancehuntAuditClient(Protocol):
    def list_threads(self) -> list[FreelancehuntThread]:
        ...

    def list_my_bids(self) -> list[FreelancehuntMyBid]:
        ...


@dataclass(frozen=True)
class FreelancehuntApiAudit:
    checked_at: str
    threads_total: int = 0
    unread_threads: int = 0
    linked_threads: int = 0
    bids_total: int = 0
    winning_bids: int = 0
    linked_bids: int = 0
    bid_statuses: dict[str, int] | None = None
    errors: list[str] | None = None


def should_send_status_report(*, store: OrderStore, interval_minutes: int) -> bool:
    path = _status_report_state_path(store)
    if interval_minutes <= 0 or not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sent_at = datetime.fromisoformat(str(payload["sent_at_iso"]))
    except Exception:
        return True
    return datetime.now(MOSCOW_TZ) - sent_at >= timedelta(minutes=interval_minutes)


def audit_freelancehunt_api(*, store: OrderStore, client: FreelancehuntAuditClient | None) -> FreelancehuntApiAudit:
    errors: list[str] = []
    threads: list[FreelancehuntThread] = []
    bids: list[FreelancehuntMyBid] = []
    if client is None:
        errors.append("Freelancehunt client is not configured")
    else:
        try:
            threads = client.list_threads()
        except Exception as exc:
            errors.append(f"threads: {_format_api_error(exc)}")
        try:
            bids = client.list_my_bids()
        except Exception as exc:
            errors.append(f"bids: {_format_api_error(exc)}")

    bid_statuses = Counter((bid.status or "unknown").lower() for bid in bids)
    return FreelancehuntApiAudit(
        checked_at=format_moscow_time(),
        threads_total=len(threads),
        unread_threads=sum(1 for thread in threads if thread.is_unread),
        linked_threads=sum(1 for thread in threads if find_order_for_thread(store, thread) is not None),
        bids_total=len(bids),
        winning_bids=sum(1 for bid in bids if bid.is_winner),
        linked_bids=sum(1 for bid in bids if _find_order_for_project_id(store, bid.project_id)),
        bid_statuses=dict(sorted(bid_statuses.items())),
        errors=errors,
    )


def build_status_report_text(*, store: OrderStore, audit: FreelancehuntApiAudit) -> str:
    status_counts = Counter(order.status.value for order in store.list_orders())
    status_lines = "\n".join(f"- {status}: {count}" for status, count in sorted(status_counts.items())) or "- заказов нет"
    bid_lines = (
        ", ".join(f"{status}: {count}" for status, count in (audit.bid_statuses or {}).items()) or "нет"
    )
    error_lines = "\n".join(f"- {error}" for error in (audit.errors or [])) or "- нет"
    linked_total = audit.linked_threads + audit.linked_bids
    return (
        "Статус агента\n\n"
        f"Время: {audit.checked_at}\n\n"
        "Локальные заказы:\n"
        f"{status_lines}\n\n"
        "API Freelancehunt:\n"
        f"- Треды: {audit.threads_total}, непрочитанные: {audit.unread_threads}\n"
        f"- Ставки: {audit.bids_total}, победившие: {audit.winning_bids}\n"
        f"- Связано с заказами: {linked_total}\n"
        f"- Статусы ставок: {bid_lines}\n\n"
        "Ошибки API:\n"
        f"{error_lines}"
    )


def write_status_report_snapshot(*, store: OrderStore, audit: FreelancehuntApiAudit, text: str) -> None:
    reports_dir = store.orders_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "freelancehunt_live_api_audit.json").write_text(
        json.dumps(asdict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "status_report.md").write_text(text.strip() + "\n", encoding="utf-8")


def mark_status_report_sent(*, store: OrderStore) -> None:
    path = _status_report_state_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sent_at": format_moscow_time(),
                "sent_at_iso": datetime.now(MOSCOW_TZ).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _status_report_state_path(store: OrderStore):
    return store.orders_dir / "reports" / "status_report_state.json"


def _format_api_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        return f"{type(exc).__name__} {status_code}"
    return type(exc).__name__


def _find_order_for_project_id(store: OrderStore, project_id: str | None) -> bool:
    if not project_id:
        return False
    for order in store.list_orders():
        if order.contact and order.contact.channel == "freelancehunt" and order.contact.value == project_id:
            return True
        if f"/{project_id}.html" in order.source_url or f"/{project_id}" in order.source_url:
            return True
    return False
