from vacancy_monitor.execution import prepare_execution_workspace
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post
from vacancy_monitor.order_store import OrderStore


def test_prepare_execution_workspace_creates_category_runbook(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/telegram-bot/123456.html",
            url="https://freelancehunt.com/project/telegram-bot/123456.html",
            text="Нужен Telegram-бот для приема заявок и записи в Google Sheets.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Telegram-боты",
        risks=[],
    )
    store.save_order(order)

    path = prepare_execution_workspace(store=store, order=order)

    assert path.name == "execution"
    checklist = (path / "checklist.md").read_text(encoding="utf-8")
    assert "Telegram-бот" in checklist
    assert "ТЗ" in checklist
    context = (path / "context.md").read_text(encoding="utf-8")
    assert order.source_url in context


def test_prepare_execution_workspace_does_not_overwrite_manual_edits(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/parser/777.html",
            url="https://freelancehunt.com/project/parser/777.html",
            text="Нужен парсер каталога.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
        risks=[],
    )
    store.save_order(order)
    path = prepare_execution_workspace(store=store, order=order)
    (path / "checklist.md").write_text("ручная правка\n", encoding="utf-8")

    prepare_execution_workspace(store=store, order=order)

    assert (path / "checklist.md").read_text(encoding="utf-8") == "ручная правка\n"
