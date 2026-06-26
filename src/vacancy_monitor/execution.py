from __future__ import annotations

import re
import shutil
import json
from dataclasses import dataclass
from pathlib import Path

from vacancy_monitor.order_models import Order, format_moscow_time
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.task_router import TaskType, route_order_task


@dataclass(frozen=True)
class ExecutionDraftPackage:
    summary_ru: str
    files: dict[str, str]
    delivery_message_ru: str


def prepare_execution_workspace(*, store: OrderStore, order: Order) -> Path:
    execution_dir = store.order_dir(order.order_id) / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    _write_if_missing(execution_dir / "context.md", _context_markdown(order))
    _write_if_missing(execution_dir / "checklist.md", _checklist_markdown(order))
    _write_if_missing(execution_dir / "notes.md", _notes_markdown(order))
    _write_task_route(execution_dir, order)
    _write_starter_artifacts(execution_dir, order)
    return execution_dir


def write_execution_draft_package(
    *,
    store: OrderStore,
    order: Order,
    package: ExecutionDraftPackage,
) -> list[Path]:
    order_dir = store.order_dir(order.order_id)
    generated_dir = order_dir / "execution" / "generated"
    outbox_dir = order_dir / "outbox"
    generated_dir.mkdir(parents=True, exist_ok=True)
    outbox_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    _write_if_missing(generated_dir / "summary.md", package.summary_ru.strip() + "\n")
    written.append(generated_dir / "summary.md")
    for raw_name, content in package.files.items():
        filename = _safe_generated_filename(raw_name)
        path = generated_dir / filename
        _write_if_missing(path, content.rstrip() + "\n")
        written.append(path)
    (outbox_dir / "delivery_message.md").write_text(package.delivery_message_ru.strip() + "\n", encoding="utf-8")
    return written


def replace_execution_draft_package(
    *,
    store: OrderStore,
    order: Order,
    package: ExecutionDraftPackage,
) -> list[Path]:
    generated_dir = store.order_dir(order.order_id) / "execution" / "generated"
    if generated_dir.exists():
        shutil.rmtree(generated_dir)
    return write_execution_draft_package(store=store, order=order, package=package)


def read_execution_draft_package(*, store: OrderStore, order: Order) -> ExecutionDraftPackage:
    order_dir = store.order_dir(order.order_id)
    generated_dir = order_dir / "execution" / "generated"
    summary_path = generated_dir / "summary.md"
    files = {
        path.relative_to(generated_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(generated_dir.rglob("*"))
        if path.is_file() and path != summary_path
    }
    return ExecutionDraftPackage(
        summary_ru=summary_path.read_text(encoding="utf-8").strip() if summary_path.exists() else "",
        files=files,
        delivery_message_ru=(order_dir / "outbox" / "delivery_message.md").read_text(encoding="utf-8").strip(),
    )


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _safe_generated_filename(value: str) -> str:
    name = Path(value).name.strip() or "result.md"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    if name in {".", "..", ""}:
        return "result.md"
    return name


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
    kind = _execution_kind(order)
    if kind == TaskType.TELEGRAM_BOT.value:
        body = _telegram_bot_checklist()
    elif kind in {TaskType.SPREADSHEET.value, TaskType.DASHBOARD.value}:
        body = _spreadsheet_checklist()
    elif kind == TaskType.CONTENT.value:
        body = _content_checklist()
    elif kind == TaskType.WEBSITE.value:
        body = _website_checklist()
    else:
        body = _automation_checklist()
    return f"# Чеклист выполнения\n\n{body}\n"


def _execution_kind(order: Order) -> str:
    return route_order_task(order).task_type.value


def _write_starter_artifacts(execution_dir: Path, order: Order) -> None:
    kind = _execution_kind(order)
    if kind == TaskType.TELEGRAM_BOT.value:
        _write_telegram_bot_starter(execution_dir, order)
    elif kind in {TaskType.SPREADSHEET.value, TaskType.DASHBOARD.value}:
        _write_spreadsheet_starter(execution_dir, order)
    elif kind == TaskType.CONTENT.value:
        _write_content_starter(execution_dir, order)
    elif kind == TaskType.WEBSITE.value:
        _write_website_starter(execution_dir, order)
    else:
        _write_automation_starter(execution_dir, order)


def _write_task_route(execution_dir: Path, order: Order) -> None:
    route = route_order_task(order)
    payload = route.to_dict()
    payload["created_at"] = format_moscow_time()
    (execution_dir / "task_route.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _website_checklist() -> str:
    return (
        "- [ ] Выписать структуру страниц и блоков.\n"
        "- [ ] Подготовить HTML/CSS/JS или проект сайта.\n"
        "- [ ] Проверить адаптивность базовых экранов.\n"
        "- [ ] Убедиться, что все ссылки и формы описаны.\n"
        "- [ ] Подготовить инструкцию локального просмотра и сообщение заказчику.\n"
    )


def _write_telegram_bot_starter(execution_dir: Path, order: Order) -> None:
    starter_dir = execution_dir / "starter"
    starter_dir.mkdir(exist_ok=True)
    _write_if_missing(starter_dir / "requirements.txt", "python-telegram-bot==21.7\npython-dotenv==1.0.1\n")
    _write_if_missing(starter_dir / ".env.example", "TELEGRAM_BOT_TOKEN=\n")
    _write_if_missing(starter_dir / "README.md", _starter_readme(order, "Telegram-бот"))
    _write_if_missing(
        starter_dir / "bot.py",
        '''from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Здравствуйте! Опишите заявку одним сообщением.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    await update.message.reply_text(
        "Заявка принята. Я свяжусь с вами после проверки данных.\\n\\n"
        f"Ваше сообщение: {text[:500]}"
    )


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
''',
    )


def _write_automation_starter(execution_dir: Path, order: Order) -> None:
    starter_dir = execution_dir / "starter"
    starter_dir.mkdir(exist_ok=True)
    _write_if_missing(starter_dir / "requirements.txt", "requests==2.32.3\nbeautifulsoup4==4.12.3\npython-dotenv==1.0.1\n")
    _write_if_missing(starter_dir / ".env.example", "SOURCE_URL=\nOUTPUT_PATH=output.csv\n")
    _write_if_missing(starter_dir / "README.md", _starter_readme(order, "Автоматизация/парсер с CSV-выгрузкой"))
    _write_if_missing(
        starter_dir / "parser.py",
        '''from __future__ import annotations

import csv
import os

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


load_dotenv()


def fetch_items(source_url: str) -> list[dict[str, str]]:
    response = requests.get(source_url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else source_url
    return [{"title": title, "url": source_url}]


def write_csv(items: list[dict[str, str]], output_path: str) -> None:
    fieldnames = sorted({key for item in items for key in item})
    with open(output_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(items)


def main() -> None:
    source_url = os.environ["SOURCE_URL"]
    output_path = os.environ.get("OUTPUT_PATH", "output.csv")
    write_csv(fetch_items(source_url), output_path)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
''',
    )


def _write_spreadsheet_starter(execution_dir: Path, order: Order) -> None:
    drafts_dir = execution_dir / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    _write_if_missing(
        drafts_dir / "spreadsheet_spec.md",
        (
            "# Структура таблицы и дашборда\n\n"
            "## Листы\n\n"
            "- `Данные`: сырые входные данные.\n"
            "- `Справочники`: статусы, категории, источники.\n"
            "- `Дашборд`: ключевые метрики и графики.\n\n"
            "## Метрики\n\n"
            "- Количество записей.\n"
            "- Сумма/среднее значение по ключевым числовым полям.\n"
            "- Динамика по датам.\n\n"
            "## Что уточнить\n\n"
            "- Формат исходных данных.\n"
            "- Нужные фильтры и группировки.\n"
            "- Кто будет обновлять таблицу.\n"
        ),
    )


def _write_content_starter(execution_dir: Path, order: Order) -> None:
    drafts_dir = execution_dir / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    _write_if_missing(
        drafts_dir / "content_draft.md",
        (
            "# Черновик текста\n\n"
            "## Цель\n\n"
            "Подготовить материал по ТЗ заказчика.\n\n"
            "## Структура\n\n"
            "1. Заголовок.\n"
            "2. Короткое вступление.\n"
            "3. Основные тезисы.\n"
            "4. Вывод или призыв к действию.\n\n"
            "## Черновик\n\n"
            "[Текст будет доработан после уточнения темы, аудитории и тона.]\n"
        ),
    )


def _write_website_starter(execution_dir: Path, order: Order) -> None:
    starter_dir = execution_dir / "starter"
    starter_dir.mkdir(exist_ok=True)
    _write_if_missing(starter_dir / "README.md", _starter_readme(order, "Сайт/лендинг"))
    _write_if_missing(
        starter_dir / "index.html",
        """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Проект</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main>
    <h1>Проект</h1>
    <p>Стартовая структура сайта. Текст и блоки нужно адаптировать под ТЗ заказчика.</p>
  </main>
</body>
</html>
""",
    )
    _write_if_missing(
        starter_dir / "styles.css",
        """body {
  margin: 0;
  font-family: Arial, sans-serif;
  color: #1f2933;
  background: #f7f8fa;
}

main {
  max-width: 960px;
  margin: 0 auto;
  padding: 48px 20px;
}
""",
    )


def _starter_readme(order: Order, title: str) -> str:
    return (
        f"# {title}\n\n"
        f"Заказ: {order.order_id}\n"
        f"Источник: {order.source_url}\n\n"
        "## Запуск\n\n"
        "1. Создать виртуальное окружение.\n"
        "2. Установить зависимости: `pip install -r requirements.txt`.\n"
        "3. Скопировать `.env.example` в `.env` и заполнить значения.\n"
        "4. Запустить основной файл.\n\n"
        "## Важно\n\n"
        "Не хранить токены, пароли и клиентские секреты в коде.\n"
        "Перед сдачей проверить основной сценарий вручную.\n"
    )
