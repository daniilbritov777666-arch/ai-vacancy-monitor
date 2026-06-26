from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
import json

import pytest

from vacancy_monitor.order_store import InvalidOrderTransition, OrderStore


def make_post() -> Post:
    return Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )


def test_save_order_writes_state_and_index(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])

    store.save_order(order)

    assert (tmp_path / "orders" / order.order_id / "state.json").exists()
    index = store.load_index()
    assert index["orders"][0]["order_id"] == order.order_id
    assert index["orders"][0]["status"] == OrderStatus.AWAITING_RESPONSE_APPROVAL.value


def test_update_status_persists_order_and_index(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)

    updated = store.update_status(order.order_id, OrderStatus.MANUAL_SEND_NEEDED)

    assert updated.status == OrderStatus.MANUAL_SEND_NEEDED
    assert store.load_order(order.order_id).status == OrderStatus.MANUAL_SEND_NEEDED
    assert store.load_index()["orders"][0]["status"] == "manual_send_needed"
    transition_log = tmp_path / "orders" / order.order_id / "transitions.jsonl"
    payload = json.loads(transition_log.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["from_status"] == "awaiting_response_approval"
    assert payload["to_status"] == "manual_send_needed"


def test_update_status_rejects_invalid_transition(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)
    store.update_status(order.order_id, OrderStatus.CLOSED)

    with pytest.raises(InvalidOrderTransition):
        store.update_status(order.order_id, OrderStatus.DRAFT_READY)


def test_rebuild_index_uses_state_files_as_source_of_truth(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)
    (tmp_path / "orders" / "index.json").write_text('{"orders": []}\n', encoding="utf-8")

    rebuilt = store.rebuild_index()

    assert rebuilt["orders"][0]["order_id"] == order.order_id
