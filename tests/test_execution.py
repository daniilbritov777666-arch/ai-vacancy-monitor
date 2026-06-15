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
    starter_dir = path / "starter"
    assert (starter_dir / "bot.py").exists()
    assert "python-telegram-bot" in (starter_dir / "requirements.txt").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" in (starter_dir / ".env.example").read_text(encoding="utf-8")


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


def test_prepare_execution_workspace_creates_parser_starter(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/parser/777.html",
            url="https://freelancehunt.com/project/parser/777.html",
            text="Нужен парсер каталога с сохранением результата в CSV.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
        risks=[],
    )
    store.save_order(order)

    path = prepare_execution_workspace(store=store, order=order)

    starter_dir = path / "starter"
    assert (starter_dir / "parser.py").exists()
    assert "requests" in (starter_dir / "requirements.txt").read_text(encoding="utf-8")
    assert "CSV" in (starter_dir / "README.md").read_text(encoding="utf-8")


def test_prepare_execution_workspace_creates_content_draft(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/text/888.html",
            url="https://freelancehunt.com/project/text/888.html",
            text="Нужно написать статью для блога на 3000 знаков.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Тексты/контент",
        risks=[],
    )
    store.save_order(order)

    path = prepare_execution_workspace(store=store, order=order)

    assert (path / "drafts" / "content_draft.md").exists()
    assert "Черновик текста" in (path / "drafts" / "content_draft.md").read_text(encoding="utf-8")


def test_prepare_execution_workspace_creates_spreadsheet_spec(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/dashboard/999.html",
            url="https://freelancehunt.com/project/dashboard/999.html",
            text="Нужен дашборд в Google Sheets по продажам.",
            published_at="2026-06-01T12:00:00+03:00",
        ),
        category="Таблицы и дашборды",
        risks=[],
    )
    store.save_order(order)

    path = prepare_execution_workspace(store=store, order=order)

    assert (path / "drafts" / "spreadsheet_spec.md").exists()
    assert "Структура таблицы" in (path / "drafts" / "spreadsheet_spec.md").read_text(encoding="utf-8")
