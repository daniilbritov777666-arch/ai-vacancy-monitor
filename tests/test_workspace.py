from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post
from vacancy_monitor.workspace import create_order_workspace


def test_create_order_workspace_writes_ru_files(tmp_path):
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=["уточнить доступы"])

    create_order_workspace(tmp_path / "orders", order)

    order_dir = tmp_path / "orders" / order.order_id
    assert "Исходный заказ" in (order_dir / "brief.md").read_text(encoding="utf-8")
    assert "История переписки" in (order_dir / "conversation.md").read_text(encoding="utf-8")
    assert "Задача для Codex/ChatGPT" in (order_dir / "prompt.md").read_text(encoding="utf-8")
    assert (order_dir / "deliverables").is_dir()


def test_create_order_workspace_does_not_overwrite_manual_edits(tmp_path):
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=[])
    order_dir = create_order_workspace(tmp_path / "orders", order)
    (order_dir / "prompt.md").write_text("ручная правка\n", encoding="utf-8")

    create_order_workspace(tmp_path / "orders", order)

    assert (order_dir / "prompt.md").read_text(encoding="utf-8") == "ручная правка\n"
