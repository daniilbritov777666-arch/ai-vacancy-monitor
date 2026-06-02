from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vacancy_monitor.order_models import Order, OrderStatus


class CallbackAction(StrEnum):
    APPROVE_OUTREACH = "approve_outreach"
    EDIT = "edit"
    REJECT = "reject"
    SENT_MANUALLY = "sent_manually"
    APPROVE_TERMS = "approve_terms"
    REQUEST_CHANGES = "request_changes"
    DRAFT_READY = "draft_ready"
    ALLOW_SENDING = "allow_sending"
    PAYMENT_NEEDED = "payment_needed"
    CLOSE = "close"


@dataclass(frozen=True)
class ParsedCallback:
    action: CallbackAction
    order_id: str


ACTION_CODES = {
    CallbackAction.APPROVE_OUTREACH: "ao",
    CallbackAction.EDIT: "e",
    CallbackAction.REJECT: "r",
    CallbackAction.SENT_MANUALLY: "sm",
    CallbackAction.APPROVE_TERMS: "at",
    CallbackAction.REQUEST_CHANGES: "rc",
    CallbackAction.DRAFT_READY: "dr",
    CallbackAction.ALLOW_SENDING: "as",
    CallbackAction.PAYMENT_NEEDED: "pn",
    CallbackAction.CLOSE: "c",
}

CODE_ACTIONS = {value: key for key, value in ACTION_CODES.items()}


def parse_callback_data(value: str) -> ParsedCallback:
    prefix, action, order_id = value.split(":", 2)
    if prefix == "o":
        return ParsedCallback(action=CODE_ACTIONS[action], order_id=order_id)
    if prefix == "order":
        return ParsedCallback(action=CallbackAction(action), order_id=order_id)
    raise ValueError("unsupported callback prefix")


def build_order_keyboard(order: Order) -> dict:
    return {
        "inline_keyboard": [
            [
                _button("Одобрить отклик", CallbackAction.APPROVE_OUTREACH, order),
                _button("Править", CallbackAction.EDIT, order),
            ],
            [
                _button("Отклонить", CallbackAction.REJECT, order),
                _button("Отправлено вручную", CallbackAction.SENT_MANUALLY, order),
            ],
            [
                _button("Согласовать условия", CallbackAction.APPROVE_TERMS, order),
                _button("Попросить правки", CallbackAction.REQUEST_CHANGES, order),
            ],
            [
                _button("Черновик готов", CallbackAction.DRAFT_READY, order),
                _button("Разрешить отправку", CallbackAction.ALLOW_SENDING, order),
            ],
            [
                _button("Оплата нужна", CallbackAction.PAYMENT_NEEDED, order),
                _button("Закрыть заказ", CallbackAction.CLOSE, order),
            ],
        ]
    }


def resolve_transition(
    *,
    action: CallbackAction,
    current_status: OrderStatus,
    can_auto_send: bool,
) -> OrderStatus | None:
    if action == CallbackAction.CLOSE:
        return OrderStatus.CLOSED
    if action == CallbackAction.REJECT and current_status == OrderStatus.AWAITING_RESPONSE_APPROVAL:
        return OrderStatus.CLOSED
    if action == CallbackAction.APPROVE_OUTREACH and current_status == OrderStatus.AWAITING_RESPONSE_APPROVAL:
        return OrderStatus.OUTREACH_SENT if can_auto_send else OrderStatus.MANUAL_SEND_NEEDED
    if action == CallbackAction.SENT_MANUALLY and current_status == OrderStatus.MANUAL_SEND_NEEDED:
        return OrderStatus.DISCOVERY
    if action == CallbackAction.APPROVE_TERMS and current_status == OrderStatus.AWAITING_TERMS_APPROVAL:
        return OrderStatus.DRAFT_READY
    if action == CallbackAction.DRAFT_READY and current_status == OrderStatus.DRAFT_READY:
        return OrderStatus.AWAITING_DELIVERY_APPROVAL
    if action == CallbackAction.ALLOW_SENDING and current_status == OrderStatus.AWAITING_DELIVERY_APPROVAL:
        return OrderStatus.PAYMENT_REQUESTED
    if action == CallbackAction.PAYMENT_NEEDED and current_status in {
        OrderStatus.AWAITING_DELIVERY_APPROVAL,
        OrderStatus.PAYMENT_REQUESTED,
    }:
        return OrderStatus.PAYMENT_REQUESTED
    return None


def _button(text: str, action: CallbackAction, order: Order) -> dict:
    return {"text": text, "callback_data": f"o:{ACTION_CODES[action]}:{order.order_id}"}
