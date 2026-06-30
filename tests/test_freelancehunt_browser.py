import json
import subprocess

import pytest

from vacancy_monitor.freelancehunt_browser import (
    BrowserBidRequest,
    BrowserCaptchaRequired,
    BrowserSessionUnauthenticated,
    FreelancehuntBrowserClient,
)


def make_request() -> BrowserBidRequest:
    return BrowserBidRequest(
        order_id="20260630-freelancehunt-1",
        project_id="1638582",
        project_url="https://freelancehunt.com/project/example/1638582.html",
        amount=6500,
        currency="UAH",
        days=3,
        safe_type="employer",
        comment="Здравствуйте! Готов выполнить задачу по этапам.",
    )


def test_browser_client_runs_dry_run_without_submit(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "dry_run", "project_id": "1638582", "submitted": False}),
            stderr="",
        )

    client = FreelancehuntBrowserClient(
        profile_dir=tmp_path / "profile",
        artifacts_dir=tmp_path / "artifacts",
        live_submit=False,
        runner=runner,
    )

    result = client.submit_bid(make_request())

    assert result.status == "dry_run"
    assert result.submitted is False
    payload = json.loads(calls[0][1]["input"])
    assert payload["live_submit"] is False
    assert payload["request"]["amount"] == 6500
    assert calls[0][1]["timeout"] == 120


def test_browser_client_returns_verified_submission(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "submitted",
                    "project_id": "1638582",
                    "submitted": True,
                    "bid_reference": "bid-16340000",
                }
            ),
            stderr="",
        )

    client = FreelancehuntBrowserClient(
        profile_dir=tmp_path / "profile",
        artifacts_dir=tmp_path / "artifacts",
        live_submit=True,
        runner=runner,
    )

    result = client.submit_bid(make_request())

    assert result.submitted is True
    assert result.bid_reference == "bid-16340000"


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        ("unauthenticated", BrowserSessionUnauthenticated),
        ("captcha_required", BrowserCaptchaRequired),
    ],
)
def test_browser_client_maps_blocked_worker_statuses(tmp_path, status, error_type):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            2,
            stdout=json.dumps({"status": status, "project_id": "1638582", "submitted": False}),
            stderr="",
        )

    client = FreelancehuntBrowserClient(
        profile_dir=tmp_path / "profile",
        artifacts_dir=tmp_path / "artifacts",
        live_submit=True,
        runner=runner,
    )

    with pytest.raises(error_type):
        client.submit_bid(make_request())


def test_browser_client_accepts_already_submitted_as_idempotent_success(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "already_submitted",
                    "project_id": "1638582",
                    "submitted": True,
                    "bid_reference": "existing-bid",
                }
            ),
            stderr="",
        )

    client = FreelancehuntBrowserClient(
        profile_dir=tmp_path / "profile",
        artifacts_dir=tmp_path / "artifacts",
        live_submit=True,
        runner=runner,
    )

    assert client.submit_bid(make_request()).status == "already_submitted"
