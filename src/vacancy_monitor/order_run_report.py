from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vacancy_monitor.order_models import Order, format_moscow_time
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import load_payment_ledger


def write_order_run_report(*, store: OrderStore, order: Order) -> Path:
    order_dir = store.order_dir(order.order_id)
    payload = {
        "order_id": order.order_id,
        "status": order.status.value,
        "category": order.category,
        "source": order.source,
        "source_url": order.source_url,
        "price_rub": order.price_rub,
        "deadline_ru": order.deadline_ru,
        "updated_at": format_moscow_time(),
        "contact": order.contact.__dict__ if order.contact else None,
        "artifacts": _collect_artifacts(order_dir),
        "payment": load_payment_ledger(store=store, order=order),
    }
    path = order_dir / "order_run_report.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _collect_artifacts(order_dir: Path) -> dict[str, Any]:
    artifacts = {
        "conversation": _relative_if_exists(order_dir, order_dir / "conversation.md"),
        "autopilot_analysis": _relative_if_exists(order_dir, order_dir / "autopilot" / "analysis.json"),
        "outreach": _relative_if_exists(order_dir, order_dir / "autopilot" / "outreach.md"),
        "send_failure": _relative_if_exists(order_dir, order_dir / "outbox" / "send_failure.json"),
        "delivery_message": _relative_if_exists(order_dir, order_dir / "outbox" / "delivery_message.md"),
        "delivery_receipt": _relative_if_exists(order_dir, order_dir / "outbox" / "delivery_receipt.json")
        or _relative_if_exists(order_dir, order_dir / "outbox" / "delivery_message.sent.json"),
        "payment_request": _relative_if_exists(order_dir, order_dir / "payment" / "request.json"),
        "payment_reminders": _relative_if_exists(order_dir, order_dir / "payment" / "reminders.json"),
        "freelancehunt_bid": _relative_if_exists(order_dir, order_dir / "payment" / "freelancehunt_bid.json"),
        "quality_report": _relative_if_exists(order_dir, order_dir / "quality" / "review.json"),
        "execution_package": _relative_if_exists(order_dir, order_dir / "execution" / "package.json"),
    }
    return {key: value for key, value in artifacts.items() if value is not None}


def _relative_if_exists(order_dir: Path, path: Path) -> str | None:
    if not path.exists():
        return None
    return str(path.relative_to(order_dir))
