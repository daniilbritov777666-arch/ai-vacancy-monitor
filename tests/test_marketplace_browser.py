import json
from pathlib import Path
from subprocess import CompletedProcess

from vacancy_monitor.marketplace_browser import (
    BrowserConversationRequest,
    BrowserOutreachRequest,
    BrowserReplyRequest,
    MarketplaceBrowserClient,
)


def test_client_runs_worker_with_safe_payload(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout='{"status":"dry_run","submitted":false,"order_id":"order-1"}', stderr="")

    client = MarketplaceBrowserClient(
        profile_dir=tmp_path / "profile",
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        headless=False,
        live_submit=False,
        timeout_seconds=90,
        runner=runner,
    )
    request = BrowserOutreachRequest(
        order_id="order-1",
        channel="freelance_ru",
        project_url="https://freelance.ru/task/view/4171",
        message="Готов выполнить задачу.",
        amount_rub=12000,
        days=3,
    )

    result = client.submit(request, artifacts_dir=tmp_path / "artifacts")

    payload = json.loads(calls[0][1]["input"])
    assert result["status"] == "dry_run"
    assert calls[0][0][-1] == "vacancy_monitor.marketplace_browser_worker"
    assert payload["operation"] == "submit_outreach"
    assert payload["live_submit"] is False
    assert payload["request"] == {
        "order_id": "order-1",
        "channel": "freelance_ru",
        "project_url": "https://freelance.ru/task/view/4171",
        "message": "Готов выполнить задачу.",
        "amount_rub": 12000,
        "days": 3,
    }
    assert payload["profile_dir"] == str(tmp_path / "profile")


def test_client_lists_messages_with_conversation_payload(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout='{"status":"ok","messages":[]}', stderr="")

    client = MarketplaceBrowserClient(
        profile_dir=tmp_path / "profile",
        executable_path="chrome",
        headless=True,
        live_submit=True,
        timeout_seconds=30,
        runner=runner,
    )
    request = BrowserConversationRequest(
        order_id="order-2",
        channel="freelance_ru",
        project_url="https://freelance.ru/task/view/4172",
    )

    result = client.list_messages(request, artifacts_dir=tmp_path / "artifacts")

    payload = json.loads(calls[0][1]["input"])
    assert result == {"status": "ok", "messages": []}
    assert payload["operation"] == "list_messages"
    assert payload["request"] == {
        "order_id": "order-2",
        "channel": "freelance_ru",
        "project_url": "https://freelance.ru/task/view/4172",
    }


def test_client_sends_reply_with_reply_payload(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout='{"status":"sent","submitted":true}', stderr="")

    client = MarketplaceBrowserClient(
        profile_dir=tmp_path / "profile",
        executable_path="chrome",
        headless=True,
        live_submit=True,
        timeout_seconds=30,
        runner=runner,
    )
    request = BrowserReplyRequest(
        order_id="order-3",
        channel="freelance_ru",
        project_url="https://freelance.ru/task/view/4173",
        message="Спасибо, приступаю.",
    )

    result = client.send_reply(request, artifacts_dir=tmp_path / "artifacts")

    payload = json.loads(calls[0][1]["input"])
    assert result == {"status": "sent", "submitted": True}
    assert payload["operation"] == "send_reply"
    assert payload["request"] == {
        "order_id": "order-3",
        "channel": "freelance_ru",
        "project_url": "https://freelance.ru/task/view/4173",
        "message": "Спасибо, приступаю.",
    }
