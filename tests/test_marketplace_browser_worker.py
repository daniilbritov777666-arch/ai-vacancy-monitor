from pathlib import Path

from vacancy_monitor.marketplace_browser import BrowserOutreachRequest
from vacancy_monitor.marketplace_browser_worker import PlaywrightOutreachPage, execute_outreach, selectors_for


def request(channel="freelance_ru"):
    return BrowserOutreachRequest(
        order_id="order-1",
        channel=channel,
        project_url="https://freelance.ru/task/view/4171",
        message="Здравствуйте! Готов выполнить задачу.",
        amount_rub=12000,
        days=3,
    )


class FakePage:
    def __init__(self, *, auth=False, captcha=False, reference=None):
        self.auth = auth
        self.captcha = captcha
        self.reference = reference
        self.calls = []

    def open(self, url):
        self.calls.append(("open", url))

    def auth_required(self):
        return self.auth

    def captcha_required(self):
        return self.captcha

    def fill(self, outreach):
        self.calls.append(("fill", outreach.channel, outreach.message))

    def screenshot(self, path):
        self.calls.append(("screenshot", Path(path).name))

    def submit(self):
        self.calls.append(("submit",))

    def submission_reference(self):
        return self.reference


def test_supported_marketplaces_have_distinct_selector_contracts():
    assert selectors_for("fl_ru").login_url == "https://www.fl.ru/login/"
    assert selectors_for("freelance_ru").login_url == "https://freelance.ru/login/"
    assert selectors_for("weblancer").login_url == "https://www.weblancer.net/account/login/"


def test_dry_run_fills_and_screenshots_without_submit(tmp_path):
    page = FakePage()

    result = execute_outreach(page=page, request=request(), artifacts_dir=tmp_path, live_submit=False)

    assert result == {"status": "dry_run", "submitted": False, "order_id": "order-1"}
    assert ("fill", "freelance_ru", "Здравствуйте! Готов выполнить задачу.") in page.calls
    assert ("screenshot", "browser_outreach_before.png") in page.calls
    assert ("submit",) not in page.calls


def test_auth_and_captcha_stop_before_fill(tmp_path):
    auth_result = execute_outreach(page=FakePage(auth=True), request=request(), artifacts_dir=tmp_path, live_submit=True)
    captcha_page = FakePage(captcha=True)
    captcha_result = execute_outreach(page=captcha_page, request=request(), artifacts_dir=tmp_path, live_submit=True)

    assert auth_result["status"] == "auth_required"
    assert captcha_result["status"] == "captcha_required"
    assert not any(call[0] == "fill" for call in captcha_page.calls)


def test_live_submit_requires_verified_reference(tmp_path):
    unverified = execute_outreach(page=FakePage(), request=request(), artifacts_dir=tmp_path, live_submit=True)
    verified = execute_outreach(
        page=FakePage(reference="response-4171"),
        request=request(),
        artifacts_dir=tmp_path,
        live_submit=True,
    )

    assert unverified["status"] == "submission_unverified"
    assert verified == {
        "status": "submitted",
        "submitted": True,
        "order_id": "order-1",
        "reference": "response-4171",
    }


def test_playwright_page_detects_cloudflare_and_login_marker():
    class Locator:
        def __init__(self, count):
            self._count = count

        def count(self):
            return self._count

    class RawPage:
        url = "https://freelance.ru/task/view/4171?__cf_chl_rt_tk=token"

        def title(self):
            return "Один момент…"

        def locator(self, selector):
            return Locator(1 if "/login" in selector else 0)

    page = PlaywrightOutreachPage(RawPage(), selectors_for("freelance_ru"))

    assert page.captcha_required() is True
    assert page.auth_required() is True
