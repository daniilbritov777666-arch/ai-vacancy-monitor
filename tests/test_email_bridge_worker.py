import json

from vacancy_monitor.email_bridge_worker import send_email_payload


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append(("send_message", message))


def test_email_bridge_worker_sends_secret_payload_over_ssl():
    instances = []

    def factory(host, port, timeout):
        instance = FakeSMTP(host, port, timeout)
        instances.append(instance)
        return instance

    payload = json.dumps(
        {
            "to": "client@example.ru",
            "subject": "Отклик на проект: Telegram-боты",
            "text": "Готов выполнить проект.",
            "message_id": "<job@example.ru>",
        },
        ensure_ascii=False,
    )

    send_email_payload(
        payload,
        host="smtp.yandex.ru",
        port=465,
        username="robot@example.ru",
        password="secret",
        from_email="robot@example.ru",
        use_ssl=True,
        smtp_ssl_factory=factory,
    )

    message = instances[0].calls[-1][1]
    assert message["To"] == "client@example.ru"
    assert message["Subject"] == "Отклик на проект: Telegram-боты"
    assert message["Message-ID"] == "<job@example.ru>"
    assert instances[0].calls[0] == ("login", "robot@example.ru", "secret")
