from dataclasses import replace

from vacancy_monitor.customer_intent import CustomerIntent
from vacancy_monitor.email_inbound import (
    EmailInboundMessage,
    IMAPEmailClient,
    build_email_notification,
    parse_email_message,
    sync_email_messages_to_order,
    write_email_reply_draft,
)
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore


RAW_EMAIL = (
    "From: Client <client@example.ru>\n"
    "To: robot@example.ru\n"
    "Subject: =?utf-8?b?UmU6INCe0YLQutC70LjQuiDQvdCwINC/0YDQvtC10LrRgg==?=\n"
    "Message-ID: <msg-1@example.ru>\n"
    "Date: Tue, 23 Jun 2026 10:30:00 +0300\n"
    "Content-Type: text/plain; charset=utf-8\n"
    "\n"
    "Здравствуйте, сможете начать сегодня?\n"
)


def test_parse_email_message_extracts_sender_subject_and_text():
    message = parse_email_message(RAW_EMAIL.encode("utf-8"))

    assert message.message_id == "msg-1@example.ru"
    assert message.from_email == "client@example.ru"
    assert message.subject == "Re: Отклик на проект"
    assert "сможете начать сегодня" in message.text
    assert message.created_at


class FakeIMAP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def select(self, folder):
        self.calls.append(("select", folder))

    def search(self, charset, criteria):
        self.calls.append(("search", charset, criteria))
        return "OK", [b"101"]

    def fetch(self, uid, query):
        self.calls.append(("fetch", uid, query))
        return "OK", [(b"101", RAW_EMAIL.encode("utf-8"))]

    def store(self, uid, flags, value):
        self.calls.append(("store", uid, flags, value))
        return "OK", []

    def logout(self):
        self.calls.append(("logout",))


def test_imap_client_peeks_unseen_messages_and_marks_seen_after_processing():
    instances = []

    def imap_factory(host, port, timeout):
        instance = FakeIMAP(host, port, timeout)
        instances.append(instance)
        return instance

    client = IMAPEmailClient(
        host="imap.example.ru",
        port=993,
        username="robot@example.ru",
        password="secret",
        imap_factory=imap_factory,
    )

    messages = client.list_unseen_messages()
    client.mark_seen(messages[0].message_id)

    assert instances[0].calls[3] == ("fetch", b"101", "(BODY.PEEK[])")
    assert ("store", b"101", "+FLAGS", "\\Seen") in instances[1].calls


def test_sync_email_messages_to_order_writes_inbox_and_conversation(tmp_path):
    store = OrderStore(tmp_path / "orders")
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:3272",
        url="https://freelance.ru/task/view/3272",
        text="Нужен Telegram-бот. client@example.ru",
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты"), status=OrderStatus.OUTREACH_SENT)
    store.save_order(order)
    messages = [
        EmailInboundMessage(
            message_id="msg-1@example.ru",
            from_email="client@example.ru",
            subject="Re: project",
            text="Можно начать сегодня?",
            created_at="23.06.2026 10:30 МСК",
            raw={"uid": "101"},
        )
    ]

    updated = sync_email_messages_to_order(store=store, order=order, messages=messages)

    order_dir = store.order_dir(order.order_id)
    assert updated.status == OrderStatus.DISCOVERY
    assert (order_dir / "inbox" / "email_client_example_ru.json").exists()
    conversation = (order_dir / "conversation.md").read_text(encoding="utf-8")
    assert "Email client@example.ru" in conversation
    assert "Можно начать сегодня?" in conversation
    intent = (order_dir / "inbox" / "customer_intent.json").read_text(encoding="utf-8")
    assert CustomerIntent.REQUIREMENTS_CLARIFICATION.value in intent


def test_build_email_notification_mentions_latest_message():
    order = make_order_from_post(
        Post(
            source="freelance.ru",
            post_id="freelance_ru:3272",
            url="https://freelance.ru/task/view/3272",
            text="Нужен парсер. client@example.ru",
            published_at="2026-06-20T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
    )
    message = EmailInboundMessage(
        message_id="msg-2@example.ru",
        from_email="client@example.ru",
        subject="Parser",
        text="Сколько будет стоить?",
        created_at="23.06.2026 10:35 МСК",
        raw={},
    )

    text = build_email_notification(order=order, messages=[message])

    assert "Ответ заказчика по email" in text
    assert order.order_id in text
    assert "Сколько будет стоить?" in text


def test_write_email_reply_draft_creates_outbox_file(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(
        Post(
            source="freelance.ru",
            post_id="freelance_ru:3272",
            url="https://freelance.ru/task/view/3272",
            text="Нужен парсер. client@example.ru",
            published_at="2026-06-20T12:00:00+03:00",
        ),
        category="Автоматизации/парсеры",
    )
    store.save_order(order)

    path = write_email_reply_draft(
        store=store,
        order=order,
        recipient="client@example.ru",
        reply_text="Здравствуйте! Могу начать сегодня.",
    )

    assert path.name == "email_reply_client_example_ru.md"
    assert "Могу начать сегодня" in path.read_text(encoding="utf-8")
