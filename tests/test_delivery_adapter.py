import json
import zipfile
from dataclasses import replace

from vacancy_monitor.delivery_adapter import build_delivery_payload
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import CustomerContact, make_order_from_post
from vacancy_monitor.order_store import OrderStore


def test_build_delivery_payload_for_freelancehunt_thread_adds_package_note(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://freelancehunt.com/project/parser/123456.html",
        url="https://freelancehunt.com/project/parser/123456.html",
        text="Нужен парсер данных.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Парсеры", risks=[])
    store.save_order(order)
    generated_dir = store.order_dir(order.order_id) / "execution" / "generated"
    generated_dir.mkdir(parents=True)
    (generated_dir / "parser.py").write_text("print('ready')\n", encoding="utf-8")
    (store.order_dir(order.order_id) / "quality").mkdir()
    (store.order_dir(order.order_id) / "quality" / "latest.json").write_text(
        json.dumps({"passed": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = build_delivery_payload(store=store, order=order, message_text="Отправляю результат.")

    assert payload.channel == "freelancehunt"
    assert payload.delivery_mode == "thread_message"
    assert payload.attachment_supported is False
    assert "Отправляю результат." in payload.message_text
    assert "Пакет результата" in payload.message_text
    assert "execution/generated/parser.py" in payload.generated_files
    assert payload.manifest_path == "outbox/delivery_package_manifest.json"
    assert payload.fallback_path == "outbox/delivery_fallback.md"
    assert payload.archive_path == "outbox/delivery_package.zip"
    archive_path = store.order_dir(order.order_id) / payload.archive_path
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "execution/generated/parser.py" in names
    assert "outbox/delivery_message.md" in names
    assert "outbox/delivery_package_manifest.json" in names


def test_build_delivery_payload_for_email_uses_email_message_mode(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelance_ru",
        post_id="freelance_ru:email",
        url="https://www.freelance.ru/project/email",
        text="Нужна таблица. Почта client@example.ru",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Таблицы", risks=[])
    order = replace(order, contact=CustomerContact("email", "client@example.ru", True))
    store.save_order(order)

    payload = build_delivery_payload(store=store, order=order, message_text="Готово.")

    assert payload.channel == "email"
    assert payload.delivery_mode == "email_message"
    assert payload.attachment_supported is False
