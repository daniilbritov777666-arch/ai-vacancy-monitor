import json
from pathlib import Path
from subprocess import CompletedProcess

from vacancy_monitor.marketplace_browser import BrowserOutreachRequest, MarketplaceBrowserClient


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
    assert payload["live_submit"] is False
    assert payload["request"]["channel"] == "freelance_ru"
    assert payload["profile_dir"] == str(tmp_path / "profile")
