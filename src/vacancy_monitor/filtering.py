from __future__ import annotations

import re

from vacancy_monitor.models import MatchResult, Post


POSITIVE_PATTERNS = {
    "сайты/лендинги": [
        r"\bлендинг",
        r"\blanding\b",
        r"tilda|тильд",
        r"wordpress|вордпресс",
        r"webflow",
        r"taplink|таплинк",
        r"\bсайт\b",
    ],
    "боты": [
        r"telegram[-\s]?бот",
        r"тг[-\s]?бот",
        r"чат[-\s]?бот",
        r"\bбот(а|ов|ы)?\b",
        r"mini\s?app|miniapp|мини[-\s]?апп",
    ],
    "автоматизация/интеграции": [
        r"автоматизац",
        r"интеграц",
        r"\bapi\b",
        r"webhook",
        r"zapier",
        r"make\.com",
        r"\bn8n\b",
        r"парсер|парсинг",
        r"скрипт",
    ],
    "crm/no-code": [
        r"\bcrm\b",
        r"битрикс|bitrix",
        r"\bamo\b|amocrm",
        r"воронк",
        r"робот",
        r"триггер",
    ],
    "таблицы/дашборды": [
        r"google sheets",
        r"\bexcel\b",
        r"таблиц",
        r"формул",
        r"макрос",
        r"дашборд|dashboard",
    ],
    "можно без глубокого кода": [
        r"без сложного кода",
        r"без кода",
        r"быстро собрать",
        r"простая задача",
    ],
}

NEGATIVE_PATTERNS = {
    "senior/middle/fulltime": [
        r"\bsenior\b",
        r"\bmiddle\b",
        r"\bfull[\s-]?time\b",
        r"фулл[\s-]?тайм",
        r"полный день",
        r"офис",
        r"опыт\s+\d+\+?\s*(лет|года|год)",
        r"kubernetes",
        r"highload",
    ],
    "долгосрочная занятость": [
        r"постоянн",
        r"долгосроч",
        r"\b5/2\b",
        r"полная занятость",
        r"частичная занятость",
        r"оклад",
        r"в штат",
        r"ежемесячн",
        r"каждый месяц",
        r"постоянная поддержка",
        r"вести на постоянной поддержке",
    ],
    "контент/smm/маркетинг": [
        r"\bsmm\b",
        r"копирайт",
        r"контент",
        r"контент[-\s]?план",
        r"пост(ы|ов)?\b",
        r"стать[ьяи]",
        r"сценари",
        r"\bseo\b",
        r"маркетолог|маркетинг",
        r"таргет",
        r"\bads\b",
        r"рекламн(ая|ые|ых|ую) кампани",
        r"авитолог",
        r"reels|shorts",
        r"монтаж",
        r"\bвидео\b",
        r"субтитр",
        r"презентац",
        r"дизайн",
        r"баннер",
        r"логотип",
        r"инфограф",
        r"карточк",
        r"\bfigma\b",
        r"\bcanva\b",
    ],
    "нет фиксированной оплаты": [
        r"без оклада",
        r"только процент",
        r"без фикс",
        r"вложения",
        r"инвестиц",
    ],
    "сложная разработка": [
        r"микросервис",
        r"архитектор",
        r"devops",
        r"c\+\+",
        r"java\s+developer",
        r"golang",
    ],
}


def evaluate_post(post: Post) -> MatchResult:
    text = post.text.lower()
    risks: list[str] = []

    for risk, patterns in NEGATIVE_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            risks.append(risk)

    reasons: list[str] = []
    for reason, patterns in POSITIVE_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            reasons.append(reason)

    has_money_signal = bool(re.search(r"(\d[\d\s]{2,}\s*(₽|руб|р\.|k|к))|бюджет|оплат", text))
    if has_money_signal:
        reasons.append("есть сигнал оплаты")

    has_technical_signal = any(reason != "есть сигнал оплаты" for reason in reasons)
    score = len(reasons)
    accepted = has_technical_signal and has_money_signal and not risks
    return MatchResult(accepted=accepted, score=score, reasons=reasons, risks=risks)


def format_match_message(post: Post, result: MatchResult) -> str:
    preview = _clean_preview(post.text, limit=650)
    reasons = ", ".join(result.reasons) if result.reasons else "похоже на простую задачу"
    risks = ", ".join(result.risks) if result.risks else "низкий или средний, уточнить ТЗ и оплату заранее"

    return (
        "🔥 Подходит\n\n"
        f"Источник: {post.source}\n"
        f"Ссылка: {post.url}\n\n"
        f"Задача:\n{preview}\n\n"
        f"Почему можно взять: {reasons}.\n\n"
        "Что я помогу сделать: разобрать ТЗ, составить план, написать код/настройки/автоматизацию, "
        "подготовить результат и ответ заказчику.\n\n"
        "Сколько просить: если бюджет не указан, начинай с маленького фиксированного этапа "
        "от 5 000 до 20 000 руб. в зависимости от объема.\n\n"
        f"Риск: {risks}.\n\n"
        "Отклик заказчику:\n"
        "Привет! Готов взять задачу. Могу быстро уточнить ТЗ, предложить понятный план и "
        "сделать первый результат небольшим фиксированным этапом. Напишите, пожалуйста, "
        "какой дедлайн и какой бюджет заложен?"
    )


def _clean_preview(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
