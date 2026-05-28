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
    assert "лендинг" in result.reasons
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


def test_formats_actionable_telegram_message():
    post = make_post("Нужно настроить CRM Bitrix24: воронка, роботы, триггеры. Бюджет 20000.")
    result = evaluate_post(post)

    message = format_match_message(post, result)

    assert "Подходит" in message
    assert "Что я помогу сделать" in message
    assert "Отклик заказчику" in message
    assert post.url in message
