from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vacancy_monitor.marketplace_browser import BrowserOutreachRequest


@dataclass(frozen=True)
class MarketplaceSelectors:
    login_url: str
    login_markers: tuple[str, ...]
    message: str
    amount: str
    days: str
    submit: str


SELECTORS = {
    "fl_ru": MarketplaceSelectors(
        login_url="https://www.fl.ru/login/",
        login_markers=('a[href*="/login"]',),
        message='textarea[name*="descr"], textarea[name*="message"], textarea',
        amount='input[name*="cost"], input[name*="price"]',
        days='input[name*="days"], input[name*="time"]',
        submit='button[type="submit"], input[type="submit"]',
    ),
    "freelance_ru": MarketplaceSelectors(
        login_url="https://freelance.ru/login/",
        login_markers=('a[href*="/login"]',),
        message='textarea[name*="comment"], textarea[name*="message"], textarea',
        amount='input[name*="price"], input[name*="budget"]',
        days='input[name*="days"], input[name*="term"]',
        submit='button[type="submit"], input[type="submit"]',
    ),
    "weblancer": MarketplaceSelectors(
        login_url="https://www.weblancer.net/account/login/",
        login_markers=('a[href*="/account/login"]',),
        message='textarea[name*="description"], textarea[name*="message"], textarea',
        amount='input[name*="cost"], input[name*="price"]',
        days='input[name*="days"], input[name*="term"]',
        submit='button[type="submit"], input[type="submit"]',
    ),
}


class OutreachPage(Protocol):
    def open(self, url: str) -> None: ...
    def auth_required(self) -> bool: ...
    def captcha_required(self) -> bool: ...
    def fill(self, request: BrowserOutreachRequest) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def submit(self) -> None: ...
    def submission_reference(self) -> str | None: ...


class BrowserLayoutError(RuntimeError):
    pass


class PlaywrightOutreachPage:
    CAPTCHA_SELECTOR = 'iframe[src*="captcha"], .g-recaptcha, input[name*="captcha"]'

    def __init__(self, page, selectors: MarketplaceSelectors) -> None:
        self.page = page
        self.selectors = selectors
        self.form = None

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    def auth_required(self) -> bool:
        if any(marker in self.page.url for marker in ("/login", "/signin", "/auth")):
            return True
        return any(self.page.locator(selector).count() > 0 for selector in self.selectors.login_markers)

    def captcha_required(self) -> bool:
        title = self.page.title().strip().lower()
        if "__cf_chl_" in self.page.url or title == "just a moment..." or title.startswith("один момент"):
            return True
        return self.page.locator(self.CAPTCHA_SELECTOR).count() > 0

    def fill(self, request: BrowserOutreachRequest) -> None:
        message = _unique(self.page.locator(self.selectors.message), "outreach message")
        self.form = message.locator("xpath=ancestor::form[1]")
        if self.form.count() != 1:
            raise BrowserLayoutError("outreach form not found")
        message.fill(request.message)
        _fill_optional_unique(self.form.locator(self.selectors.amount), str(request.amount_rub), "amount")
        _fill_optional_unique(self.form.locator(self.selectors.days), str(request.days), "days")

    def screenshot(self, path: Path) -> None:
        self.page.screenshot(path=str(path), full_page=True)

    def submit(self) -> None:
        if self.form is None:
            raise BrowserLayoutError("outreach form was not prepared")
        _unique(self.form.locator(self.selectors.submit), "outreach submit").click()
        self.page.wait_for_timeout(1500)

    def submission_reference(self) -> str | None:
        success = self.page.get_by_text(
            re.compile(r"отклик.*отправ|предложение.*добав|заявка.*отправ", re.IGNORECASE)
        )
        if success.count() == 1:
            return "submitted"
        return None


def selectors_for(channel: str) -> MarketplaceSelectors:
    try:
        return SELECTORS[channel]
    except KeyError as exc:
        raise ValueError(f"unsupported browser marketplace: {channel}") from exc


def execute_outreach(
    *,
    page: OutreachPage,
    request: BrowserOutreachRequest,
    artifacts_dir: Path,
    live_submit: bool,
) -> dict:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    page.open(request.project_url)
    if page.captcha_required():
        page.screenshot(artifacts_dir / "browser_captcha.png")
        return {"status": "captcha_required", "submitted": False, "order_id": request.order_id}
    if page.auth_required():
        page.screenshot(artifacts_dir / "browser_auth_required.png")
        return {"status": "auth_required", "submitted": False, "order_id": request.order_id}
    page.fill(request)
    page.screenshot(artifacts_dir / "browser_outreach_before.png")
    if not live_submit:
        return {"status": "dry_run", "submitted": False, "order_id": request.order_id}
    page.submit()
    page.screenshot(artifacts_dir / "browser_outreach_after.png")
    reference = page.submission_reference()
    if not reference:
        return {"status": "submission_unverified", "submitted": False, "order_id": request.order_id}
    return {
        "status": "submitted",
        "submitted": True,
        "order_id": request.order_id,
        "reference": reference,
    }


def _unique(locator, name: str):
    count = locator.count()
    if count != 1:
        raise BrowserLayoutError(f"{name} selector matched {count} elements")
    return locator


def _fill_optional_unique(locator, value: str, name: str) -> None:
    count = locator.count()
    if count > 1:
        raise BrowserLayoutError(f"{name} selector matched {count} elements")
    if count == 1:
        locator.fill(value)


def run_payload(payload: dict) -> dict:
    from playwright.sync_api import sync_playwright

    request = BrowserOutreachRequest(**payload["request"])
    selectors = selectors_for(request.channel)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(Path(payload["profile_dir"])),
            headless=bool(payload.get("headless", False)),
            executable_path=payload.get("executable_path") or None,
            viewport={"width": 1440, "height": 1000},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            return execute_outreach(
                page=PlaywrightOutreachPage(page, selectors),
                request=request,
                artifacts_dir=Path(payload["artifacts_dir"]),
                live_submit=bool(payload.get("live_submit", False)),
            )
        finally:
            context.close()


def main() -> int:
    try:
        result = run_payload(json.loads(sys.stdin.read()))
    except BrowserLayoutError as exc:
        result = {"status": "layout_error", "submitted": False, "error": str(exc)}
    except Exception as exc:
        result = {"status": "worker_error", "submitted": False, "error_type": type(exc).__name__}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"dry_run", "submitted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
