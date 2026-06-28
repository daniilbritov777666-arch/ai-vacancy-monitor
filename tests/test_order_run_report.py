import json
from dataclasses import replace

from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_run_report import write_order_run_report
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import build_static_payment_request, write_payment_request


def test_write_order_run_report_links_state_artifacts_and_payment(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = replace(
        make_order_from_post(
            Post(
                source="freelance_ru",
                post_id="freelance_ru:1",
                url="https://www.freelance.ru/projects/1",
                text="Нужен парсер. Почта client@example.ru. Бюджет 12 000 руб.",
                published_at="2026-06-26T12:00:00+03:00",
            ),
            category="Автоматизации/парсеры",
            risks=[],
        ),
        status=OrderStatus.PAYMENT_REQUESTED,
        price_rub=12000,
    )
    store.save_order(order)
    order_dir = store.order_dir(order.order_id)
    (order_dir / "conversation.md").write_text("Заказчик: Когда готово?\n", encoding="utf-8")
    (order_dir / "outbox").mkdir(exist_ok=True)
    (order_dir / "outbox" / "delivery_message.sent.json").write_text('{"sent": true}\n', encoding="utf-8")
    (order_dir / "outbox" / "delivery_receipt.json").write_text('{"status": "sent"}\n', encoding="utf-8")
    (order_dir / "outbox" / "freelancehunt_preflight.json").write_text('{"eligible": true}\n', encoding="utf-8")
    payment = build_static_payment_request(order=order, amount_rub=12000, instructions_ru="Оплата по СБП.")
    write_payment_request(store=store, order=order, payment=payment)
    (order_dir / "payment" / "reminders.json").write_text('{"events": []}\n', encoding="utf-8")

    path = write_order_run_report(store=store, order=order)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["order_id"] == order.order_id
    assert payload["status"] == "payment_requested"
    assert payload["price_rub"] == 12000
    assert payload["artifacts"]["conversation"] == "conversation.md"
    assert payload["artifacts"]["delivery_receipt"] == "outbox/delivery_receipt.json"
    assert payload["artifacts"]["freelancehunt_preflight"] == "outbox/freelancehunt_preflight.json"
    assert payload["artifacts"]["payment_request"] == "payment/request.json"
    assert payload["artifacts"]["payment_reminders"] == "payment/reminders.json"
    assert payload["payment"]["current_status"] == "requested"
    assert payload["payment"]["requested_amount_rub"] == 12000
