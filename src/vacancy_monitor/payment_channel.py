from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import requests

from vacancy_monitor.order_models import Order, format_moscow_time
from vacancy_monitor.order_store import OrderStore


YOOKASSA_PAYMENTS_URL = "https://api.yookassa.ru/v3/payments"


@dataclass(frozen=True)
class PaymentRequest:
    provider: str
    amount_rub: int
    order_id: str
    created_at: str
    payment_id: str | None = None
    payment_url: str | None = None
    status: str | None = None
    instructions_ru: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class YooKassaPaymentClient:
    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        return_url: str,
        session=None,
        timeout_seconds: int = 20,
    ) -> None:
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.return_url = return_url
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def create_payment(self, *, order: Order, amount_rub: int, description: str) -> PaymentRequest:
        payload = {
            "amount": {"value": _rub_value(amount_rub), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": self.return_url},
            "description": description[:128],
            "metadata": {
                "order_id": order.order_id,
                "source": order.source,
                "source_url": order.source_url,
            },
        }
        response = self.session.post(
            YOOKASSA_PAYMENTS_URL,
            auth=(self.shop_id, self.secret_key),
            headers={"Idempotence-Key": _idempotence_key(order)},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        confirmation = data.get("confirmation") or {}
        return PaymentRequest(
            provider="yookassa",
            amount_rub=amount_rub,
            order_id=order.order_id,
            created_at=format_moscow_time(),
            payment_id=data.get("id"),
            payment_url=confirmation.get("confirmation_url"),
            status=data.get("status"),
        )


def build_static_payment_request(*, order: Order, amount_rub: int, instructions_ru: str) -> PaymentRequest:
    return PaymentRequest(
        provider="static_requisites",
        amount_rub=amount_rub,
        order_id=order.order_id,
        created_at=format_moscow_time(),
        instructions_ru=instructions_ru.strip(),
    )


def write_payment_request(*, store: OrderStore, order: Order, payment: PaymentRequest):
    path = store.order_dir(order.order_id) / "payment" / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payment.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def format_payment_block(payment: PaymentRequest) -> str:
    amount = f"{payment.amount_rub:,.0f}".replace(",", " ")
    lines = [
        "",
        "---",
        "",
        "Платежный канал:",
        f"Сумма: {amount} ₽",
    ]
    if payment.payment_url:
        lines.append(f"Ссылка на оплату: {payment.payment_url}")
    if payment.instructions_ru:
        lines.append(payment.instructions_ru)
    lines.append("После оплаты я проверю статус и закрою заказ.")
    return "\n".join(lines)


def _rub_value(amount_rub: int) -> str:
    return f"{Decimal(amount_rub):.2f}"


def _idempotence_key(order: Order) -> str:
    digest = hashlib.sha1(f"{order.order_id}:payment".encode("utf-8")).hexdigest()[:16]
    return f"{order.order_id}-{digest}"[:64]
