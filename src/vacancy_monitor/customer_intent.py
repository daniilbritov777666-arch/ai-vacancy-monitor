from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class CustomerIntent(StrEnum):
    REQUIREMENTS_CLARIFICATION = "requirements_clarification"
    PRICE_NEGOTIATION = "price_negotiation"
    REVISION_REQUEST = "revision_request"
    ACCEPTANCE = "acceptance"
    PAYMENT_SIGNAL = "payment_signal"
    RISKY_REQUEST = "risky_request"
    OTHER = "other"


@dataclass(frozen=True)
class CustomerIntentResult:
    intent: CustomerIntent
    reason_ru: str
    should_auto_reply: bool = True
    requires_payment_confirmation: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["intent"] = self.intent.value
        return data


def classify_customer_messages(messages: list[str]) -> CustomerIntentResult:
    text = "\n".join(message for message in messages if message).lower()
    if not text.strip():
        return CustomerIntentResult(intent=CustomerIntent.OTHER, reason_ru="нет текста сообщения")
    if _has_any(text, _RISKY_MARKERS):
        return CustomerIntentResult(
            intent=CustomerIntent.RISKY_REQUEST,
            reason_ru="сообщение содержит рискованный запрос",
            should_auto_reply=False,
        )
    if _has_any(text, _REVISION_MARKERS):
        return CustomerIntentResult(intent=CustomerIntent.REVISION_REQUEST, reason_ru="заказчик просит правки")
    if _has_any(text, _PAYMENT_MARKERS):
        return CustomerIntentResult(
            intent=CustomerIntent.PAYMENT_SIGNAL,
            reason_ru="заказчик сообщил об оплате",
            requires_payment_confirmation=True,
        )
    if _has_any(text, _ACCEPTANCE_MARKERS):
        return CustomerIntentResult(intent=CustomerIntent.ACCEPTANCE, reason_ru="заказчик принимает результат")
    if _has_any(text, _PRICE_MARKERS):
        return CustomerIntentResult(intent=CustomerIntent.PRICE_NEGOTIATION, reason_ru="заказчик обсуждает цену")
    if _has_any(text, _REQUIREMENTS_MARKERS):
        return CustomerIntentResult(
            intent=CustomerIntent.REQUIREMENTS_CLARIFICATION,
            reason_ru="заказчик уточняет требования или сроки",
        )
    return CustomerIntentResult(intent=CustomerIntent.OTHER, reason_ru="намерение не определено")


def _has_any(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


_REVISION_MARKERS = ["правк", "поправ", "исправ", "доработ", "передел", "не работает", "ошиб", "замен", "обнов"]
_PAYMENT_MARKERS = ["оплатил", "оплатила", "оплата ушла", "перевел", "перевела", "перевёл", "чек", "квитанц"]
_ACCEPTANCE_MARKERS = ["принимаю", "принято", "все отлично", "всё отлично", "подходит", "утверждаю", "работа выполнена"]
_PRICE_MARKERS = ["цена", "стоимость", "бюджет", "дорого", "скидк", "сумм", "оплат"]
_REQUIREMENTS_MARKERS = ["когда", "срок", "дедлайн", "можете", "сможете", "начать", "тз", "что нужно", "уточн"]
_RISKY_MARKERS = [
    "обойти лимит",
    "обход лимитов",
    "массовая рассыл",
    "массовую рассыл",
    "логин и пароль",
    "логин/пароль",
    "seed",
    "private key",
    "фишинг",
    "накрут",
    "спам",
]
