from dataclasses import replace

from vacancy_monitor.email_outreach import SMTPOutreachClient
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def starttls(self, context):
        self.calls.append(("starttls", context))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append(("send_message", message))


def test_smtp_outreach_uses_tls_login_and_deterministic_message_id():
    smtp_instances = []

    def smtp_factory(host, port, timeout):
        instance = FakeSMTP(host, port, timeout)
        smtp_instances.append(instance)
        return instance

    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:3272",
        url="https://freelance.ru/task/view/3272",
        text="Нужен бот. client@example.ru",
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты"), price_rub=15000)
    client = SMTPOutreachClient(
        host="smtp.example.ru",
        port=587,
        username="robot@example.ru",
        password="secret",
        from_email="robot@example.ru",
        use_ssl=False,
        smtp_factory=smtp_factory,
    )

    client.send(order, "Здравствуйте! Готов выполнить задачу.")
    first_message = smtp_instances[0].calls[-1][1]
    client.send(order, "Здравствуйте! Готов выполнить задачу.")
    second_message = smtp_instances[1].calls[-1][1]

    assert smtp_instances[0].host == "smtp.example.ru"
    assert smtp_instances[0].calls[0][0] == "starttls"
    assert smtp_instances[0].calls[1] == ("login", "robot@example.ru", "secret")
    assert first_message["To"] == "client@example.ru"
    assert first_message["Message-ID"] == second_message["Message-ID"]


def test_smtp_outreach_attaches_delivery_archive(tmp_path):
    smtp_instances = []

    def smtp_factory(host, port, timeout):
        instance = FakeSMTP(host, port, timeout)
        smtp_instances.append(instance)
        return instance

    archive_path = tmp_path / "delivery_package.zip"
    archive_path.write_bytes(b"zip-content")
    post = Post(
        source="freelance.ru",
        post_id="freelance_ru:delivery",
        url="https://freelance.ru/task/view/delivery",
        text="Нужен парсер. client@example.ru",
        published_at="2026-06-20T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Парсеры")
    client = SMTPOutreachClient(
        host="smtp.example.ru",
        port=465,
        username="robot@example.ru",
        password="secret",
        from_email="robot@example.ru",
        use_ssl=True,
        smtp_factory=smtp_factory,
    )

    client.send(order, "Результат готов.", attachments=[archive_path])

    message = smtp_instances[0].calls[-1][1]
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "delivery_package.zip"
    assert attachments[0].get_content_type() == "application/zip"
    assert attachments[0].get_content() == b"zip-content"
