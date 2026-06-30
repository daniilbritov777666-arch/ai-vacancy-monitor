from pathlib import Path

from vacancy_monitor.freelancehunt_browser import BrowserBidRequest
from vacancy_monitor.freelancehunt_browser_worker import execute_bid


def request() -> BrowserBidRequest:
    return BrowserBidRequest(
        order_id="order-1",
        project_id="1638582",
        project_url="https://freelancehunt.com/project/example/1638582.html",
        amount=6500,
        currency="UAH",
        days=3,
        safe_type="employer",
        comment="Здравствуйте! Готов выполнить задачу.",
    )


class FakePage:
    def __init__(self, *, unauthenticated=False, captcha=False, existing=None, verified=None):
        self.unauthenticated = unauthenticated
        self.captcha = captcha
        self.existing = existing
        self.verified = verified
        self.calls = []

    def open(self, url):
        self.calls.append(("open", url))

    def is_unauthenticated(self):
        return self.unauthenticated

    def has_captcha(self):
        return self.captcha

    def existing_bid_reference(self):
        return self.existing

    def fill_bid(self, bid_request):
        self.calls.append(("fill", bid_request.amount, bid_request.days, bid_request.comment))

    def screenshot(self, path):
        self.calls.append(("screenshot", Path(path).name))

    def submit(self):
        self.calls.append(("submit",))

    def verified_bid_reference(self):
        return self.verified


def test_execute_bid_dry_run_fills_but_does_not_submit(tmp_path):
    page = FakePage()

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=False)

    assert result == {"status": "dry_run", "project_id": "1638582", "submitted": False}
    assert ("fill", 6500, 3, "Здравствуйте! Готов выполнить задачу.") in page.calls
    assert ("submit",) not in page.calls
    assert ("screenshot", "browser_bid_before.png") in page.calls


def test_execute_bid_stops_when_session_is_not_authenticated(tmp_path):
    page = FakePage(unauthenticated=True)

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert result["status"] == "unauthenticated"
    assert not any(call[0] == "fill" for call in page.calls)


def test_execute_bid_stops_on_captcha(tmp_path):
    page = FakePage(captcha=True)

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert result["status"] == "captcha_required"
    assert not any(call[0] == "submit" for call in page.calls)


def test_execute_bid_treats_existing_bid_as_idempotent_success(tmp_path):
    page = FakePage(existing="bid-16339999")

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert result["status"] == "already_submitted"
    assert result["bid_reference"] == "bid-16339999"
    assert result["submitted"] is True


def test_execute_bid_live_requires_verified_bid_reference(tmp_path):
    page = FakePage(verified=None)

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert result["status"] == "submission_unverified"
    assert result["submitted"] is False
    assert page.calls.count(("submit",)) == 1


def test_execute_bid_live_returns_verified_reference(tmp_path):
    page = FakePage(verified="bid-16340000")

    result = execute_bid(page=page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert result["status"] == "submitted"
    assert result["submitted"] is True
    assert result["bid_reference"] == "bid-16340000"
    assert ("screenshot", "browser_bid_after.png") in page.calls
