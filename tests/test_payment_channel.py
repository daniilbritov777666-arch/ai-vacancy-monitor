import json

from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import (
    YooKassaPaymentClient,
    build_static_payment_request,
    format_payment_block,
    load_payment_ledger,
    write_payment_request,
)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "payment-123",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/payments/payment-123"},
        }


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, auth, headers, json, timeout):
        self.calls.append(
            {
                "url": url,
                "auth": auth,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()


def test_yookassa_client_creates_rub_payment_link():
    session = FakeSession()
    order = make_order_from_post(
        Post(
            source="freelance_ru",
            post_id="freelance_ru/1",
            url="https://www.freelance.ru/projects/1",
            text="Нужен Telegram-бот. Пишите client@example.ru",
            published_at="2026-06-23T10:00:00+03:00",
        ),
        category="Telegram-боты",
        risks=[],
    )
    client = YooKassaPaymentClient(
        shop_id="shop-1",
        secret_key="secret",
        return_url="https://example.ru/payment-return",
        session=session,
    )

    payment = client.create_payment(order=order, amount_rub=15000, description="Оплата заказа")

    assert payment.provider == "yookassa"
    assert payment.payment_id == "payment-123"
    assert payment.payment_url == "https://yookassa.ru/payments/payment-123"
    call = session.calls[0]
    assert call["url"] == "https://api.yookassa.ru/v3/payments"
    assert call["auth"] == ("shop-1", "secret")
    assert call["headers"]["Idempotence-Key"].startswith(order.order_id)
    assert call["json"]["amount"] == {"value": "15000.00", "currency": "RUB"}
    assert call["json"]["confirmation"] == {
        "type": "redirect",
        "return_url": "https://example.ru/payment-return",
    }


def test_static_payment_request_is_written_to_order_folder(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelance_ru",
            post_id="freelance_ru/2",
            url="https://www.freelance.ru/projects/2",
            text="Нужен парсер. Почта client@example.ru",
            published_at="2026-06-23T11:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
        risks=[],
    )
    store.save_order(order)

    payment = build_static_payment_request(
        order=order,
        amount_rub=12000,
        instructions_ru="Перевод на карту РФ после проверки результата.",
    )
    path = write_payment_request(store=store, order=order, payment=payment)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["provider"] == "static_requisites"
    assert payload["amount_rub"] == 12000
    assert "Перевод на карту РФ" in format_payment_block(payment)
    ledger = load_payment_ledger(store=store, order=order)
    assert ledger["order_id"] == order.order_id
    assert ledger["current_status"] == "requested"
    assert ledger["requested_amount_rub"] == 12000
    assert ledger["confirmed_amount_rub"] == 0
    assert ledger["events"][0]["event"] == "payment_requested"
    assert ledger["events"][0]["provider"] == "static_requisites"
