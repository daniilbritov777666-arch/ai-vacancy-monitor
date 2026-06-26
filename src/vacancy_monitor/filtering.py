from __future__ import annotations

import re

from vacancy_monitor.models import MatchResult, Post


POSITIVE_PATTERNS = {
    "боты": [
        r"telegram[-\s]?бот",
        r"тг[-\s]?бот",
        r"чат[-\s]?бот",
        r"\bбот(а|ов|ы)?\b",
        r"mini\s?app|miniapp|мини[-\s]?апп",
    ],
    "автоматизация/интеграции": [
        r"автоматизац",
        r"автоматизаці",
        r"интеграц",
        r"інтеграц",
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
        r"воронк(?:а|и|у|ой)?\s+продаж|продажн\w*\s+воронк",
        r"checkout",
        r"shopify",
    ],
    "таблицы/дашборды": [
        r"google sheets",
        r"\bexcel\b",
        r"формул",
        r"макрос",
        r"дашборд|dashboard",
        r"отчет\s+по\s+заявк",
    ],
    "тексты/контент": [
        r"(?:написать|подготовить|составить|переписать|отредактировать|редактировани[ея]|вычитать|вычитка)"
        r"\s+(?:\S+\s+){0,3}(?:текст|описани[ея]|стать[ьюяи]|документ|контент)",
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
    "постоянная вакансия/подработка": [
        r"ваканси",
        r"требуется\s+(специалист|сотрудник|менеджер|ассистент)",
        r"ищем\s+(специалиста|сотрудника|менеджера|ассистента)",
        r"доход\s*:\s*от\s*\d",
        r"зарплат",
        r"свободный график",
        r"обучение предоставляется",
        r"сопровождение наставника",
        r"перспективы роста",
        r"возраст\s*18",
    ],
    "не IT-заказ": [
        r"подбор[ау]?\s+товар",
        r"маркетплейс",
        r"искать\s+поставщик",
        r"изучать\s+предложения\s+конкурент",
        r"востребованные\s+товары",
        r"пропал\s+интернет",
        r"не\s+открываются\s+.*сайт",
        r"\bword\b",
        r"\bворд\b",
        r"оформить\s+таблиц",
        r"copy[-\s]?paste",
        r"data\s+entry",
        r"ввод(?:а|у|ом)?\s+данных",
        r"копирован\w*\s+и\s+вставк\w*",
        r"копипаст",
        r"сделать\s+сайт",
        r"создани[ея]\s+.*сайт",
        r"html\s+сайт",
        r"отредактир.*сайт",
        r"поправить\s+.*сайт",
        r"сайт[-\s]?визитк",
        r"подач[аи]\s+в\s+суд",
        r"\bсуд\b",
        r"туркомпан",
        r"турагент",
    ],
    "администрирование/защита сайта": [
        r"cloudflare",
        r"\bddos\b",
        r"бот[-\s]?атак",
        r"bot[-\s]?attack",
    ],
    "контент/smm/маркетинг": [
        r"\bsmm\b",
        r"контент[-\s]?план",
        r"пост(ы|ов)?\b",
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
        r"проверка\s+и\s+редактур",
        r"редактур[аы]?.*стать",
        r"вычит.*стать",
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
    "обход ограничений платформ": [
        r"сервисн(ый|ых|ые|ого)?\s+ключ",
        r"дополнительн(ые|ых|ый)\s+.*ключ",
        r"увеличени[яе]\s+скорости\s+.*парсинг",
        r"через\s+любой\s+акк",
        r"через\s+любой\s+аккаунт",
        r"массов(о|ая|ые|ых)\s+.*аккаунт",
        r"обход\s+.*(лимит|огранич)",
    ],
    "финансовый/трейдинг риск": [
        r"pocket\s*option",
        r"трейдинг[-\s]?бот",
        r"торгов(ый|ого)\s+бот",
        r"ставк[аи]\s+.*(верн|сигнал)",
        r"\bbrent\s+oil\b",
    ],
    "массовые сообщения/автоматизация аккаунта": [
        r"1000\+?\s+предложен",
        r"массов(ая|ые|ых|о)\s+.*(сообщ|предложен|рассыл)",
        r"авторизац\w*\s+через\s+логин\s+и\s+парол",
        r"от\s+одного\s+аккаунт",
    ],
}

REASON_WEIGHTS = {
    "боты": 4,
    "автоматизация/интеграции": 3,
    "таблицы/дашборды": 2,
    "crm/no-code": 2,
    "тексты/контент": 1,
    "можно без глубокого кода": 0,
    "есть сигнал оплаты": 2,
    "оплата через биржу": 2,
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

    has_money_signal = bool(
        re.search(
            r"(\d[\d\s]{2,}\s*(₽|руб|р\.|uah|грн|₴|usd|\$|eur|€|pln|zł|k|к))|"
            r"((₽|₴|\$|€)\s*\d[\d\s]{2,})|"
            r"бюджет|оплат",
            text,
        )
    )
    if has_money_signal:
        reasons.append("есть сигнал оплаты")
    elif _is_trusted_paid_platform(post):
        has_money_signal = True
        reasons.append("оплата через биржу")

    has_technical_signal = any(
        reason not in {"есть сигнал оплаты", "оплата через биржу", "можно без глубокого кода"} for reason in reasons
    )
    if not has_technical_signal:
        risks.append("не IT-заказ")

    score = _score_match(text=text, reasons=reasons)
    accepted = has_technical_signal and has_money_signal and not risks
    return MatchResult(accepted=accepted, score=score, reasons=reasons, risks=risks)


def _is_trusted_paid_platform(post: Post) -> bool:
    source = post.source.lower()
    url = post.url.lower()
    return "freelancehunt.com" in source or "freelancehunt.com" in url


def _score_match(*, text: str, reasons: list[str]) -> int:
    score = sum(REASON_WEIGHTS.get(reason, 1) for reason in reasons)
    if re.search(r"разов(ая|ий|ое|і|ий)|готов(ый|ого)?\s+результат|фиксированн(ый|ого)?\s+этап", text):
        score += 1
    if re.search(r"срок\s+\d+|дедлайн|за\s+\d+\s*(дн|час)", text):
        score += 1
    if "тексты/контент" in reasons:
        score = min(score, 7)
    return score


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
