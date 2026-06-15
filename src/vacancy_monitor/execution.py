from __future__ import annotations

from pathlib import Path

from vacancy_monitor.order_models import Order, format_moscow_time
from vacancy_monitor.order_store import OrderStore


def prepare_execution_workspace(*, store: OrderStore, order: Order) -> Path:
    execution_dir = store.order_dir(order.order_id) / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    _write_if_missing(execution_dir / "context.md", _context_markdown(order))
    _write_if_missing(execution_dir / "checklist.md", _checklist_markdown(order))
    _write_if_missing(execution_dir / "notes.md", _notes_markdown(order))
    return execution_dir


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _context_markdown(order: Order) -> str:
    return (
        f"# Рабочий контекст заказа {order.order_id}\n\n"
        f"Создано: {format_moscow_time()}\n"
        f"Категория: {order.category}\n"
        f"Источник: {order.source_url}\n"
        f"Статус: {order.status.value}\n"
        f"Цена: {order.price_rub or 'не согласована'} руб.\n"
        f"Срок: {order.deadline_ru or 'не согласован'}\n\n"
        "## Исходное ТЗ\n\n"
        f"{order.original_text}\n\n"
        "## Где смотреть переписку\n\n"
        "- `../conversation.md`\n"
        "- `../inbox/`\n"
        "- `../outbox/`\n"
    )


def _checklist_markdown(order: Order) -> str:
    lower_category = order.category.lower()
    lower_text = order.original_text.lower()
    if "telegram" in lower_category or "бот" in lower_category or "telegram" in lower_text:
        body = _telegram_bot_checklist()
    elif "таблиц" in lower_category or "дашборд" in lower_category or "excel" in lower_text or "google sheets" in lower_text:
        body = _spreadsheet_checklist()
    elif "текст" in lower_category or "контент" in lower_category:
        body = _content_checklist()
    else:
        body = _automation_checklist()
    return f"# Чеклист выполнения\n\n{body}\n"


def _notes_markdown(order: Order) -> str:
    return (
        "# Заметки выполнения\n\n"
        "## Уточнения\n\n"
        "- \n\n"
        "## Решения\n\n"
        "- \n\n"
        "## Что сдаем заказчику\n\n"
        "- \n"
    )


def _telegram_bot_checklist() -> str:
    return (
        "- [ ] Выписать ТЗ: сценарии, команды, роли, интеграции.\n"
        "- [ ] Уточнить, где будет жить бот: локально, VPS, Railway, Render.\n"
        "- [ ] Описать структуру данных и внешние сервисы.\n"
        "- [ ] Подготовить минимальный код Telegram-бота.\n"
        "- [ ] Подготовить `.env.example` без секретов.\n"
        "- [ ] Проверить основной сценарий вручную.\n"
        "- [ ] Подготовить инструкцию запуска и сообщение заказчику.\n"
    )


def _automation_checklist() -> str:
    return (
        "- [ ] Выписать ТЗ и входные/выходные данные.\n"
        "- [ ] Уточнить ограничения источников, API и частоту запуска.\n"
        "- [ ] Подготовить скрипт/автоматизацию с настройками через `.env`.\n"
        "- [ ] Добавить логирование и обработку ошибок.\n"
        "- [ ] Проверить на тестовых данных.\n"
        "- [ ] Подготовить инструкцию запуска и сообщение заказчику.\n"
    )


def _spreadsheet_checklist() -> str:
    return (
        "- [ ] Выписать ТЗ по таблице, полям, формулам и отчетам.\n"
        "- [ ] Подготовить структуру листов и входных данных.\n"
        "- [ ] Собрать формулы, сводки или дашборд.\n"
        "- [ ] Проверить расчеты на примерах.\n"
        "- [ ] Подготовить инструкцию обновления данных.\n"
        "- [ ] Подготовить сообщение заказчику.\n"
    )


def _content_checklist() -> str:
    return (
        "- [ ] Выписать ТЗ: тема, аудитория, тон, объем, формат.\n"
        "- [ ] Собрать структуру материала.\n"
        "- [ ] Подготовить первый вариант текста.\n"
        "- [ ] Проверить факты, стиль и повторы.\n"
        "- [ ] Подготовить финальный файл и сообщение заказчику.\n"
    )
