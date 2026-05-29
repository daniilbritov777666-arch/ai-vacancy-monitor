from vacancy_monitor.filtering import evaluate_post, format_match_message
from vacancy_monitor.models import Post


def make_post(text: str) -> Post:
    return Post(
        source="test",
        post_id="test/1",
        url="https://t.me/s/test/1",
        text=text,
        published_at="2026-05-28T10:00:00+00:00",
    )


def test_accepts_ai_friendly_landing_page_task():
    post = make_post(
        "Нужен лендинг на Tilda для онлайн-школы. Есть структура, оплатим 15000, "
        "можно без сложного кода, важно быстро собрать и оформить."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert result.score >= 3
    assert "сайты/лендинги" in result.reasons
    assert "готовый отклик" not in result.reasons


def test_rejects_senior_fulltime_developer_vacancy():
    post = make_post(
        "Ищем Senior Python Backend Developer fulltime в офис. Опыт 5+ лет, "
        "Kubernetes, highload, микросервисы."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "senior/middle/fulltime" in result.risks


def test_rejects_suspicious_sales_without_fixed_pay():
    post = make_post(
        "Нужны люди в продажи без оклада, доход только процент, вложения окупаются быстро."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "нет фиксированной оплаты" in result.risks


def test_rejects_copywriting_and_smm_tasks():
    post = make_post(
        "Разовая задача: написать 10 постов для Telegram и сделать SMM-контент-план. "
        "Оплата 7000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "контент/smm/маркетинг" in result.risks


def test_rejects_long_term_remote_roles_even_when_ai_related():
    post = make_post(
        "Постоянная удаленная работа 5/2: вести AI-контент и Telegram Ads, оклад 60000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "долгосрочная занятость" in result.risks


def test_accepts_one_off_automation_task():
    post = make_post(
        "Разовая задача: сделать Telegram-бота для приема заявок, интеграция с Google Sheets, "
        "оплата 15000 руб., срок 3 дня."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert "боты" in result.reasons
    assert "автоматизация/интеграции" in result.reasons


def test_rejects_technical_task_when_it_is_long_term_support():
    post = make_post(
        "Нужен специалист по Битрикс24 на постоянную поддержку: мелкие доработки каждый месяц, "
        "оплата договорная."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "долгосрочная занятость" in result.risks


def test_formats_actionable_telegram_message():
    post = make_post("Нужно настроить CRM Bitrix24: воронка, роботы, триггеры. Бюджет 20000.")
    result = evaluate_post(post)

    message = format_match_message(post, result)

    assert "Подходит" in message
    assert "Что я помогу сделать" in message
    assert "Отклик заказчику" in message
    assert post.url in message
