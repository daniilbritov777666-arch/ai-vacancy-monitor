from dataclasses import replace

from vacancy_monitor.config import Config
from vacancy_monitor.email_transport_health import probe_email_transport, write_email_transport_health_report


def make_config(tmp_path) -> Config:
    return Config(
        bot_token="token",
        chat_id="150761046",
        channels=[],
        rss_feeds=[],
        state_path=tmp_path / "seen_posts.json",
        send_first_run=False,
        orders_path=tmp_path / "orders",
    )


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_probe_email_transport_reports_reachable_smtp_and_blocked_imap(tmp_path):
    config = replace(
        make_config(tmp_path),
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        smtp_from="robot@example.ru",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )

    def connector(address, timeout):
        host, _port = address
        if host == "imap.yandex.ru":
            raise TimeoutError("timed out")
        return FakeSocket()

    report = probe_email_transport(config=config, connector=connector, timeout_seconds=1)

    assert report.smtp_configured is True
    assert report.smtp_reachable is True
    assert report.imap_configured is True
    assert report.imap_reachable is False
    assert report.imap_error == "TimeoutError: timed out"
    assert report.status == "degraded"


def test_write_email_transport_health_report_outputs_json(tmp_path):
    config = replace(
        make_config(tmp_path),
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        smtp_from="robot@example.ru",
    )
    report = probe_email_transport(config=config, connector=lambda address, timeout: FakeSocket(), timeout_seconds=1)

    path = write_email_transport_health_report(tmp_path / "email_transport_health.json", report)

    text = path.read_text(encoding="utf-8")
    assert '"smtp_reachable": true' in text
    assert '"status": "degraded"' in text
