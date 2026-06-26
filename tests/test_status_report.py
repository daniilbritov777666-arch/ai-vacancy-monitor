from dataclasses import replace

from vacancy_monitor.freelancehunt import FreelancehuntMyBid, FreelancehuntThread
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.payment_channel import build_static_payment_request, write_payment_request
from vacancy_monitor.status_report import audit_freelancehunt_api, build_status_report_text


class FakeAuditClient:
    def list_threads(self):
        return [
            FreelancehuntThread(
                thread_id="thread-1",
                project_id="123456",
                subject="Telegram bot",
                is_unread=True,
                updated_at="2026-06-15T09:00:00+03:00",
                raw={"id": "thread-1"},
            )
        ]

    def list_my_bids(self):
        return [
            FreelancehuntMyBid(
                bid_id="bid-1",
                project_id="123456",
                status="active",
                is_winner=True,
                project_status="completed",
                raw={"id": "bid-1"},
            )
        ]


class FailingAuditClient:
    def list_threads(self):
        raise TimeoutError("threads timeout")

    def list_my_bids(self):
        error = RuntimeError("bids failed")
        error.response = type("Response", (), {"status_code": 404})()
        raise error


def test_status_report_counts_local_orders_and_api_links(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
        url="https://freelancehunt.com/project/telegram-bot/123456.html",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    store.save_order(replace(make_order_from_post(post, category="Telegram-боты", risks=[]), status=OrderStatus.CLOSED))

    audit = audit_freelancehunt_api(store=store, client=FakeAuditClient())
    text = build_status_report_text(store=store, audit=audit)

    assert audit.threads_total == 1
    assert audit.unread_threads == 1
    assert audit.linked_threads == 1
    assert audit.linked_bids == 1
    assert audit.winning_bids == 1
    assert audit.bid_statuses == {"active": 1}
    assert "closed: 1" in text
    assert "Связано с заказами: 2" in text


def test_status_report_records_api_errors(tmp_path):
    store = OrderStore(tmp_path / "orders")

    audit = audit_freelancehunt_api(store=store, client=FailingAuditClient())
    text = build_status_report_text(store=store, audit=audit)

    assert audit.errors == [
        "threads: TimeoutError",
        "bids: RuntimeError 404",
    ]
    assert "threads: TimeoutError" in text
    assert "bids: RuntimeError 404" in text


def test_status_report_includes_funnel_and_payment_ledger(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelance_ru",
        post_id="freelance_ru:1",
        url="https://www.freelance.ru/projects/1",
        text="Нужен парсер. Почта client@example.ru. Бюджет 12 000 руб.",
        published_at="2026-06-26T12:00:00+03:00",
    )
    order = replace(
        make_order_from_post(post, category="Автоматизации/парсеры", risks=[]),
        status=OrderStatus.PAYMENT_REQUESTED,
        price_rub=12000,
    )
    store.save_order(order)
    payment = build_static_payment_request(
        order=order,
        amount_rub=12000,
        instructions_ru="Оплата по СБП.",
    )
    write_payment_request(store=store, order=order, payment=payment)

    audit = audit_freelancehunt_api(store=store, client=None)
    text = build_status_report_text(store=store, audit=audit)

    assert "Воронка:" in text
    assert "- Ожидают оплаты: 1" in text
    assert "Деньги:" in text
    assert "- Запрошено: 12 000 ₽" in text
    assert "- Подтверждено: 0 ₽" in text
