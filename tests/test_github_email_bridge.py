from dataclasses import replace

from vacancy_monitor.github_email_bridge import GitHubEmailBridge

from test_local_agent_cli import make_config
from vacancy_monitor.order_models import CustomerContact, OrderStatus, make_order_from_post
from vacancy_monitor.models import Post


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []
        self.run_checks = 0

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/actions/secrets/public-key"):
            return FakeResponse({"key_id": "key-id", "key": "public-key"})
        self.run_checks += 1
        runs = []
        if self.run_checks > 1:
            runs = [{"name": "email-bridge-job-123", "status": "completed", "conclusion": "success"}]
        return FakeResponse({"workflow_runs": runs})

    def put(self, url, **kwargs):
        self.calls.append(("put", url, kwargs))
        return FakeResponse(status_code=201)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse(status_code=204)


def test_github_email_bridge_encrypts_payload_dispatches_and_waits(tmp_path):
    config = replace(make_config(tmp_path), smtp_from="robot@example.ru")
    post = Post(
        source="freelance_ru",
        post_id="email-project-1",
        url="https://example.ru/project/1",
        text="Нужен Telegram-бот. Контакт: client@example.ru",
        published_at="2026-06-30T10:00:00+03:00",
    )
    order = replace(make_order_from_post(post, category="Telegram-боты"), status=OrderStatus.DRAFT_READY)
    assert order.contact == CustomerContact(channel="email", value="client@example.ru", can_auto_send=True)
    session = FakeSession()
    encrypted = []

    bridge = GitHubEmailBridge(
        repo="owner/repo",
        token="github-token",
        workflow="email-bridge.yml",
        dispatch_ref="main",
        source_ref="codex/public-project-sources",
        from_email="robot@example.ru",
        session=session,
        encryptor=lambda key, payload: encrypted.append((key, payload)) or "sealed-payload",
        sleep=lambda _: None,
        job_id_factory=lambda: "job-123",
    )

    bridge.send(order, "Готов выполнить проект.")

    assert encrypted[0][0] == "public-key"
    assert b'"to": "client@example.ru"' in encrypted[0][1]
    put_call = next(call for call in session.calls if call[0] == "put")
    assert put_call[2]["json"] == {"encrypted_value": "sealed-payload", "key_id": "key-id"}
    post_call = next(call for call in session.calls if call[0] == "post")
    assert post_call[2]["json"] == {
        "ref": "main",
        "inputs": {"job_id": "job-123", "source_ref": "codex/public-project-sources"},
    }


def test_github_email_bridge_rejects_attachments(tmp_path):
    config = replace(make_config(tmp_path), smtp_from="robot@example.ru")
    post = Post(
        source="freelance_ru",
        post_id="email-project-2",
        url="https://example.ru/project/2",
        text="Контакт: client@example.ru",
        published_at="2026-06-30T10:00:00+03:00",
    )
    order = make_order_from_post(post, category="Автоматизация")
    bridge = GitHubEmailBridge(
        repo="owner/repo",
        token="token",
        workflow="email-bridge.yml",
        dispatch_ref="main",
        source_ref="branch",
        from_email="robot@example.ru",
        session=FakeSession(),
    )

    try:
        bridge.send(order, "text", attachments=[tmp_path / "result.zip"])
    except ValueError as exc:
        assert "attachments" in str(exc)
    else:
        raise AssertionError("attachments must be rejected")
