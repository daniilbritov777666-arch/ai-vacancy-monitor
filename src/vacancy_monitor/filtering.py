from __future__ import annotations

import re

from vacancy_monitor.models import MatchResult, Post


POSITIVE_KEYWORDS = {
    "лендинг": ["лендинг", "landing", "tilda", "таплинк", "taplink", "сайт", "webflow"],
    "telegram": ["telegram бот", "тг бот", "бот", "mini app", "мини апп", "miniapp"],
    "автоматизация": ["автоматизац", "zapier", "make.com", "n8n", "интеграц", "парсинг", "скрипт"],
    "crm": ["crm", "битрикс", "bitrix", "amo", "воронк", "робот", "триггер"],
    "контент": ["копирайт", "seo", "текст", "пост", "контент", "сценари", "статья"],
    "дизайн": ["дизайн", "инфограф", "карточк", "canva", "figma", "аватар", "обложк"],
    "нейросети": ["нейросет", "chatgpt", "gpt", "ai", "ии", "midjourney", "stable diffusion"],
    "монтаж": ["reels", "shorts", "монтаж", "видео", "субтитр"],
    "таблицы": ["google sheets", "excel", "таблиц", "дашборд", "отчет"],
    "можно без глубокого кода": ["без сложного кода", "без кода", "быстро собрать", "простая задача"],
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
    for reason, words in POSITIVE_KEYWORDS.items():
        if any(word in text for word in words):
            reasons.append(reason)

    has_money_signal = bool(re.search(r"(\d[\d\s]{2,}\s*(₽|руб|р\.|k|к))|бюджет|оплат", text))
    if has_money_signal:
        reasons.append("есть сигнал оплаты")

    score = len(reasons)
    accepted = score >= 2 and not risks
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
        "Что я помогу сделать: разобрать ТЗ, составить план, написать код/тексты/промпты, "
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
