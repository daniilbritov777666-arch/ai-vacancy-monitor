from __future__ import annotations

from pathlib import Path

from vacancy_monitor.order_models import Order


def create_order_workspace(orders_dir: Path, order: Order) -> Path:
    order_dir = orders_dir / order.order_id
    order_dir.mkdir(parents=True, exist_ok=True)
    (order_dir / "deliverables").mkdir(exist_ok=True)

    _write_if_missing(order_dir / "brief.md", _brief_markdown(order))
    _write_if_missing(order_dir / "conversation.md", _conversation_markdown(order))
    _write_if_missing(order_dir / "prompt.md", _prompt_markdown(order))

    return order_dir


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _brief_markdown(order: Order) -> str:
    risks = "\n".join(f"- {risk}" for risk in order.risks) if order.risks else "- Не выявлены"
    return (
        f"# Заказ {order.order_id}\n\n"
        "## Исходный заказ\n\n"
        f"Источник: {order.source}\n"
        f"Ссылка: {order.source_url}\n"
        f"Категория: {order.category}\n"
        f"Создано: {order.created_at}\n\n"
        "## Текст\n\n"
        f"{order.original_text}\n\n"
        "## Риски\n\n"
        f"{risks}\n"
    )


def _conversation_markdown(order: Order) -> str:
    return (
        f"# История переписки по заказу {order.order_id}\n\n"
        f"Создано: {order.created_at}\n\n"
        "## Исходное сообщение заказчика\n\n"
        f"{order.original_text}\n"
    )


def _prompt_markdown(order: Order) -> str:
    return (
        "# Задача для Codex/ChatGPT\n\n"
        "Ты помогаешь выполнить фриланс-заказ в РФ-формате. Ответы и документы готовь "
        "на русском языке. Суммы указывай в рублях, даты в формате ДД.ММ.ГГГГ.\n\n"
        f"## Заказ\n\nID: {order.order_id}\n"
        f"Категория: {order.category}\n"
        f"Источник: {order.source_url}\n\n"
        "## Исходное ТЗ\n\n"
        f"{order.original_text}\n\n"
        "## Что нужно сделать\n\n"
        "1. Разобрать требования заказчика.\n"
        "2. Предложить короткий план выполнения.\n"
        "3. Подготовить черновик результата или список уточняющих вопросов.\n"
        "4. Не обещать цену, срок или гарантии без подтверждения Даниила.\n"
    )
