from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from vacancy_monitor.order_models import Order, OrderStatus, format_moscow_time


class InvalidOrderTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.AWAITING_RESPONSE_APPROVAL, OrderStatus.SKIPPED, OrderStatus.CLOSED},
    OrderStatus.AWAITING_RESPONSE_APPROVAL: {
        OrderStatus.OUTREACH_SENT,
        OrderStatus.MANUAL_SEND_NEEDED,
        OrderStatus.DRAFT_READY,
        OrderStatus.SKIPPED,
        OrderStatus.CLOSED,
    },
    OrderStatus.MANUAL_SEND_NEEDED: {OrderStatus.DISCOVERY, OrderStatus.OUTREACH_SENT, OrderStatus.CLOSED},
    OrderStatus.SEND_FAILED: {OrderStatus.DRAFT_READY, OrderStatus.CLOSED},
    OrderStatus.DRAFT_READY: {
        OrderStatus.OUTREACH_SENT,
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
        OrderStatus.CONTACT_UNAVAILABLE,
        OrderStatus.SEND_FAILED,
        OrderStatus.SKIPPED,
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.QUALITY_FAILED,
    },
    OrderStatus.OUTREACH_SENT: {
        OrderStatus.DISCOVERY,
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.SEND_FAILED,
        OrderStatus.CLOSED,
    },
    OrderStatus.DISCOVERY: {
        OrderStatus.DRAFT_READY,
        OrderStatus.AWAITING_TERMS_APPROVAL,
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.QUALITY_FAILED,
        OrderStatus.CLOSED,
    },
    OrderStatus.AWAITING_TERMS_APPROVAL: {OrderStatus.DRAFT_READY, OrderStatus.CLOSED},
    OrderStatus.AWAITING_DELIVERY_APPROVAL: {
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.QUALITY_FAILED,
        OrderStatus.CLOSED,
    },
    OrderStatus.PAYMENT_REQUESTED: {
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.QUALITY_FAILED,
        OrderStatus.CLOSED,
    },
    OrderStatus.QUALITY_FAILED: {
        OrderStatus.DRAFT_READY,
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
        OrderStatus.PAYMENT_REQUESTED,
        OrderStatus.CLOSED,
    },
    OrderStatus.CONTACT_UNAVAILABLE: {OrderStatus.CLOSED},
    OrderStatus.SKIPPED: {OrderStatus.CLOSED},
    OrderStatus.CLOSED: set(),
}


class OrderStore:
    def __init__(self, orders_dir: Path):
        self.orders_dir = orders_dir
        self.index_path = orders_dir / "index.json"

    def order_dir(self, order_id: str) -> Path:
        return self.orders_dir / order_id

    def state_path(self, order_id: str) -> Path:
        return self.order_dir(order_id) / "state.json"

    def save_order(self, order: Order) -> None:
        self.order_dir(order.order_id).mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.state_path(order.order_id), order.to_dict())
        self._upsert_index(order)

    def load_order(self, order_id: str) -> Order:
        return Order.from_dict(_read_json(self.state_path(order_id)))

    def load_index(self) -> dict:
        if not self.index_path.exists():
            return {"orders": []}
        return _read_json(self.index_path)

    def list_orders(self) -> list[Order]:
        return [
            Order.from_dict(_read_json(path))
            for path in sorted(self.orders_dir.glob("*/state.json"))
        ]

    def update_status(self, order_id: str, status: OrderStatus) -> Order:
        order = self.load_order(order_id)
        _validate_transition(order.status, status)
        updated = replace(order, status=status, updated_at=format_moscow_time())
        self.save_order(updated)
        self._append_transition(order=order, updated=updated)
        return updated

    def rebuild_index(self) -> dict:
        orders = [Order.from_dict(_read_json(path)) for path in self.orders_dir.glob("*/state.json")]
        index = {"orders": [_index_entry(order) for order in sorted(orders, key=lambda item: item.created_at)]}
        _write_json_atomic(self.index_path, index)
        return index

    def _upsert_index(self, order: Order) -> None:
        index = self.load_index()
        entry = _index_entry(order)
        orders = [item for item in index.get("orders", []) if item.get("order_id") != order.order_id]
        orders.append(entry)
        index["orders"] = sorted(orders, key=lambda item: item["created_at"])
        _write_json_atomic(self.index_path, index)

    def _append_transition(self, *, order: Order, updated: Order) -> None:
        if order.status == updated.status:
            return
        path = self.order_dir(order.order_id) / "transitions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "changed_at": updated.updated_at,
            "order_id": order.order_id,
            "from_status": order.status.value,
            "to_status": updated.status.value,
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _index_entry(order: Order) -> dict:
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "source_url": order.source_url,
        "category": order.category,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _validate_transition(current: OrderStatus, next_status: OrderStatus) -> None:
    if current == next_status:
        return
    if next_status in ALLOWED_TRANSITIONS.get(current, set()):
        return
    raise InvalidOrderTransition(f"{current.value} -> {next_status.value}")
