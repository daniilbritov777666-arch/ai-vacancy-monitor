import json

from vacancy_monitor.marketplace_conversation import (
    MarketplaceMessage,
    sync_marketplace_messages,
    write_marketplace_reply_draft,
    write_marketplace_reply_sent_record,
)


def test_sync_messages_writes_each_customer_message_once(tmp_path):
    order_dir = tmp_path / "order-1"
    order_dir.mkdir()
    (order_dir / "conversation.md").write_text("# История\n", encoding="utf-8")
    messages = [
        MarketplaceMessage(
            message_id="m-7",
            author="customer",
            text="Когда начнете?",
            created_at="2026-07-01T10:00:00+03:00",
        )
    ]

    first = sync_marketplace_messages(order_dir=order_dir, channel="freelance_ru", messages=messages)
    second = sync_marketplace_messages(order_dir=order_dir, channel="freelance_ru", messages=messages)

    assert first == messages
    assert second == []
    inbox = list((order_dir / "inbox").glob("platform_*.json"))
    assert len(inbox) == 1
    assert json.loads(inbox[0].read_text(encoding="utf-8"))["message_id"] == "m-7"
    assert (order_dir / "conversation.md").read_text(encoding="utf-8").count("Когда начнете?") == 1


def test_sync_messages_uses_content_hash_without_platform_id(tmp_path):
    message = MarketplaceMessage(message_id=None, author="customer", text="Нужен срок", created_at=None)

    first = sync_marketplace_messages(order_dir=tmp_path, channel="weblancer", messages=[message])
    second = sync_marketplace_messages(order_dir=tmp_path, channel="weblancer", messages=[message])

    assert first == [message]
    assert second == []


def test_reply_draft_and_sent_record_are_written_to_outbox(tmp_path):
    draft = write_marketplace_reply_draft(
        order_dir=tmp_path,
        channel="fl_ru",
        reply_text="Начну сегодня.",
    )
    sent = write_marketplace_reply_sent_record(
        order_dir=tmp_path,
        channel="fl_ru",
        reply_text="Начну сегодня.",
        reference="reply-7",
    )

    assert draft.read_text(encoding="utf-8") == "Начну сегодня.\n"
    payload = json.loads(sent.read_text(encoding="utf-8"))
    assert payload["channel"] == "fl_ru"
    assert payload["reference"] == "reply-7"
