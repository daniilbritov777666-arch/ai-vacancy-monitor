from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore


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


def test_rebuild_index_uses_state_files_as_source_of_truth(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)
    (tmp_path / "orders" / "index.json").write_text('{"orders": []}\n', encoding="utf-8")

    rebuilt = store.rebuild_index()

    assert rebuilt["orders"][0]["order_id"] == order.order_id
