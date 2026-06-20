from dataclasses import replace

from vacancy_monitor.freelancehunt import FreelancehuntMyBid, FreelancehuntThread
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore
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
