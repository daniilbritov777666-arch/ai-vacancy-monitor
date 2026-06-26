from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from vacancy_monitor.order_models import Order


class TaskType(StrEnum):
    TELEGRAM_BOT = "telegram_bot"
    PARSER = "parser"
    CONTENT = "content"
    SPREADSHEET = "spreadsheet"
    DASHBOARD = "dashboard"
    WEBSITE = "website"
    INTEGRATION = "integration"
    AUTOMATION = "automation"


@dataclass(frozen=True)
class TaskRoute:
    task_type: TaskType
    label_ru: str
    verifier_profile: str
    confidence: float
    evidence: tuple[str, ...]
    deliverable_requirements_ru: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["task_type"] = self.task_type.value
        return data


def route_order_task(order: Order) -> TaskRoute:
    haystack = f"{order.category}\n{order.original_text}".lower()
    scored = [
        _score_route(TaskType.TELEGRAM_BOT, haystack, ("telegram", "телеграм", "бот", "bot")),
        _score_route(TaskType.PARSER, haystack, ("парсер", "парсинг", "scraper", "parser", "выгрузк", "собрать данные")),
        _score_route(TaskType.DASHBOARD, haystack, ("дашборд", "dashboard", "отчет по", "метрик")),
        _score_route(TaskType.SPREADSHEET, haystack, ("таблиц", "excel", "xlsx", "google sheets", "csv", "формул")),
        _score_route(TaskType.WEBSITE, haystack, ("сайт", "лендинг", "html", "css", "верстк", "tilda")),
        _score_route(TaskType.INTEGRATION, haystack, ("интеграц", "api", "webhook", "crm", "amo", "bitrix")),
        _score_route(TaskType.CONTENT, haystack, ("текст", "контент", "стать", "копирайт", "описани")),
    ]
    task_type, score, evidence = max(scored, key=lambda item: (item[1], _priority(item[0])))
    if score <= 0:
        task_type, score, evidence = TaskType.AUTOMATION, 0.35, ("default_automation",)
    confidence = min(0.95, max(0.35, 0.5 + score * 0.1))
    return TaskRoute(
        task_type=task_type,
        label_ru=_label_ru(task_type),
        verifier_profile=_verifier_profile(task_type),
        confidence=round(confidence, 2),
        evidence=tuple(evidence),
        deliverable_requirements_ru=_requirements(task_type),
    )


def _score_route(task_type: TaskType, haystack: str, terms: tuple[str, ...]) -> tuple[TaskType, int, list[str]]:
    evidence = [term for term in terms if term in haystack]
    score = len(evidence)
    if task_type == TaskType.DASHBOARD and evidence:
        score += 2
    return task_type, score, evidence


def _priority(task_type: TaskType) -> int:
    return {
        TaskType.TELEGRAM_BOT: 90,
        TaskType.PARSER: 80,
        TaskType.DASHBOARD: 70,
        TaskType.SPREADSHEET: 65,
        TaskType.WEBSITE: 60,
        TaskType.INTEGRATION: 55,
        TaskType.CONTENT: 50,
        TaskType.AUTOMATION: 10,
    }[task_type]


def _label_ru(task_type: TaskType) -> str:
    return {
        TaskType.TELEGRAM_BOT: "Telegram-бот",
        TaskType.PARSER: "Парсер/выгрузка данных",
        TaskType.CONTENT: "Текст/контент",
        TaskType.SPREADSHEET: "Таблица",
        TaskType.DASHBOARD: "Дашборд",
        TaskType.WEBSITE: "Сайт/лендинг",
        TaskType.INTEGRATION: "Интеграция",
        TaskType.AUTOMATION: "Автоматизация",
    }[task_type]


def _verifier_profile(task_type: TaskType) -> str:
    if task_type in {TaskType.TELEGRAM_BOT, TaskType.PARSER, TaskType.WEBSITE, TaskType.INTEGRATION, TaskType.AUTOMATION}:
        return "code"
    if task_type in {TaskType.SPREADSHEET, TaskType.DASHBOARD}:
        return "spreadsheet"
    return "content"


def _requirements(task_type: TaskType) -> tuple[str, ...]:
    return {
        TaskType.TELEGRAM_BOT: (
            "Код бота с настройками через переменные окружения.",
            "README с запуском и .env.example без секретов.",
        ),
        TaskType.PARSER: (
            "Скрипт парсинга или автоматизации.",
            "Файл результата или пример CSV/JSON.",
            "README с запуском и ограничениями источника.",
        ),
        TaskType.CONTENT: (
            "Отдельный MD/TXT файл финального текста.",
            "Текст достаточного объема по ТЗ.",
        ),
        TaskType.SPREADSHEET: (
            "Структурированный CSV/XLSX/XLS/JSON файл.",
            "Описание структуры и обновления данных.",
        ),
        TaskType.DASHBOARD: (
            "Структурированный CSV/XLSX/XLS/JSON файл с данными для дашборда.",
            "Описание метрик и способа обновления.",
        ),
        TaskType.WEBSITE: (
            "HTML/CSS/JS файлы или проект сайта.",
            "README с локальным просмотром и структурой файлов.",
        ),
        TaskType.INTEGRATION: (
            "Код интеграции с настройками через переменные окружения.",
            "README с API-параметрами без секретов.",
        ),
        TaskType.AUTOMATION: (
            "Скрипт/автоматизация с понятным запуском.",
            "README и пример входных/выходных данных.",
        ),
    }[task_type]
