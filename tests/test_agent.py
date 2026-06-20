from vacancy_monitor.agent import handle_matched_post
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_store import OrderStore


def test_handle_matched_post_creates_order_and_sends_approval_card(tmp_path):
    sent = []
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    result = MatchResult(accepted=True, score=3, reasons=["боты", "есть сигнал оплаты"], risks=[])

    order = handle_matched_post(
        post=post,
        result=result,
        store=OrderStore(tmp_path / "orders"),
        send_approval=lambda text, reply_markup: sent.append((text, reply_markup)),
    )

    assert order.status.value == "awaiting_response_approval"
    assert (tmp_path / "orders" / order.order_id / "state.json").exists()
    assert (tmp_path / "orders" / order.order_id / "prompt.md").exists()
    assert "Одобрить отклик" in str(sent[0][1])
    assert "Первый отклик" in sent[0][0]


def test_handle_matched_post_maps_known_reason_to_ru_category(tmp_path):
    sent = []
    post = Post(
        source="sample",
        post_id="sample/2",
        url="https://t.me/sample/2",
        text="Нужен парсер сайта и запись в Google Sheets. Оплата 20 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    result = MatchResult(accepted=True, score=3, reasons=["автоматизация/интеграции"], risks=[])

    order = handle_matched_post(
        post=post,
        result=result,
        store=OrderStore(tmp_path / "orders"),
        send_approval=lambda text, reply_markup: sent.append((text, reply_markup)),
    )

    assert order.category == "Автоматизации и парсеры"


def test_handle_matched_post_maps_text_content_category(tmp_path):
    sent = []
    post = Post(
        source="sample",
        post_id="sample/3",
        url="https://t.me/sample/3",
        text="Подготовить текст для страницы Telegram-бота. Бюджет 8000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    result = MatchResult(accepted=True, score=2, reasons=["тексты/контент", "есть сигнал оплаты"], risks=[])

    order = handle_matched_post(
        post=post,
        result=result,
        store=OrderStore(tmp_path / "orders"),
        send_approval=lambda text, reply_markup: sent.append((text, reply_markup)),
    )

    assert order.category == "Тексты и контент"
