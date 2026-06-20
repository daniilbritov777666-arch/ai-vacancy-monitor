from __future__ import annotations

from collections.abc import Callable

from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_models import Order, make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.telegram_control import build_order_keyboard
from vacancy_monitor.workspace import create_order_workspace

FIRST_OUTREACH_DRAFT = (
    "Здравствуйте! Готов обсудить задачу. Могу быстро уточнить ТЗ, предложить понятный план "
    "и выполнить работу фиксированным этапом. Подскажите, пожалуйста, какой дедлайн и какой "
    "бюджет заложен?"
)


def handle_matched_post(
    *,
    post: Post,
    result: MatchResult,
    store: OrderStore,
    send_approval: Callable[[str, dict], None],
) -> Order:
    order = make_order_from_post(post, category=_category_from_result(result), risks=result.risks)
    store.save_order(order)
    create_order_workspace(store.orders_dir, order)

    send_approval(_approval_card(order), build_order_keyboard(order))
    return order


def _category_from_result(result: MatchResult) -> str:
    reasons = set(result.reasons)
    if reasons & {"боты", "telegram"}:
        return "Telegram-боты"
    if reasons & {"автоматизация/интеграции", "автоматизация", "таблицы"}:
        return "Автоматизации и парсеры"
    if reasons & {"тексты/контент", "контент"}:
        return "Тексты и контент"
    if reasons & {"таблицы/дашборды"}:
        return "Таблицы и дашборды"
    return "Автоматизации и парсеры"


def _approval_card(order: Order) -> str:
    preview = order.original_text.strip()
    if len(preview) > 800:
        preview = preview[:797].rstrip() + "..."
    return (
        "🟡 Новый заказ на подтверждение\n\n"
        f"ID: {order.order_id}\n"
        f"Категория: {order.category}\n"
        f"Источник: {order.source_url}\n\n"
        f"Исходный текст:\n{preview}\n\n"
        f"Первый отклик:\n{FIRST_OUTREACH_DRAFT}\n\n"
        "Без подтверждения этот отклик клиенту не отправляется."
    )
