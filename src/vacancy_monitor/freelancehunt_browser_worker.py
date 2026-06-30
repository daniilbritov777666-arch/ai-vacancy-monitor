from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Protocol

from vacancy_monitor.freelancehunt_browser import BrowserBidRequest


class BrowserPage(Protocol):
    def open(self, url: str) -> None: ...
    def is_unauthenticated(self) -> bool: ...
    def has_captcha(self) -> bool: ...
    def existing_bid_reference(self) -> str | None: ...
    def fill_bid(self, request: BrowserBidRequest) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def submit(self) -> None: ...
    def verified_bid_reference(self) -> str | None: ...


class BrowserLayoutError(RuntimeError):
    pass


def execute_bid(
    *,
    page: BrowserPage,
    request: BrowserBidRequest,
    artifacts_dir: Path,
    live_submit: bool,
) -> dict:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    page.open(request.project_url)
    if page.is_unauthenticated():
        page.screenshot(artifacts_dir / "browser_unauthenticated.png")
        return {"status": "unauthenticated", "project_id": request.project_id, "submitted": False}
    if page.has_captcha():
        page.screenshot(artifacts_dir / "browser_captcha.png")
        return {"status": "captcha_required", "project_id": request.project_id, "submitted": False}
    existing = page.existing_bid_reference()
    if existing:
        return {
            "status": "already_submitted",
            "project_id": request.project_id,
            "submitted": True,
            "bid_reference": existing,
        }

    page.fill_bid(request)
    page.screenshot(artifacts_dir / "browser_bid_before.png")
    if not live_submit:
        return {"status": "dry_run", "project_id": request.project_id, "submitted": False}

    page.submit()
    page.screenshot(artifacts_dir / "browser_bid_after.png")
    reference = page.verified_bid_reference()
    if not reference:
        return {"status": "submission_unverified", "project_id": request.project_id, "submitted": False}
    return {
        "status": "submitted",
        "project_id": request.project_id,
        "submitted": True,
        "bid_reference": reference,
    }


class PlaywrightBidPage:
    LOGIN_SELECTOR = 'a[href="/profile/login"]'
    CAPTCHA_SELECTOR = 'iframe[src*="captcha"], .g-recaptcha, input[name*="captcha"]'
    COMMENT_SELECTOR = 'textarea[name="comment"], textarea[name$="[comment]"], textarea'
    DAYS_SELECTOR = 'input[name="days"], input[name$="[days]"]'
    AMOUNT_SELECTOR = 'input[name="amount"], input[name$="[amount]"]'
    OWN_BID_SELECTOR = '[data-own-bid="true"] a[href*="#bid-"], .bid-own a[href*="#bid-"]'

    def __init__(self, page) -> None:
        self.page = page
        self.form = None
        self.before_bid_references: set[str] = set()

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    def is_unauthenticated(self) -> bool:
        return self.page.locator(self.LOGIN_SELECTOR).count() > 0

    def has_captcha(self) -> bool:
        title = self.page.title().strip().lower()
        if "__cf_chl_" in self.page.url or title == "just a moment...":
            return True
        return self.page.locator(self.CAPTCHA_SELECTOR).count() > 0

    def existing_bid_reference(self) -> str | None:
        own = self.page.locator(self.OWN_BID_SELECTOR)
        if own.count() == 1:
            return _bid_reference(own.get_attribute("href"))
        return None

    def fill_bid(self, request: BrowserBidRequest) -> None:
        comment = _unique(self.page.locator(self.COMMENT_SELECTOR), "bid comment")
        self.form = comment.locator("xpath=ancestor::form[1]")
        if self.form.count() != 1:
            raise BrowserLayoutError("bid form not found")
        comment.fill(request.comment)
        days = _unique(self.form.locator(self.DAYS_SELECTOR), "bid days")
        amount = _unique(self.form.locator(self.AMOUNT_SELECTOR), "bid amount")
        days.fill(str(request.days))
        amount.fill(str(request.amount))
        self.before_bid_references = self._all_bid_references()

    def screenshot(self, path: Path) -> None:
        self.page.screenshot(path=str(path), full_page=True)

    def submit(self) -> None:
        if self.form is None:
            raise BrowserLayoutError("bid form was not prepared")
        submit = _unique(self.form.locator('button[type="submit"], input[type="submit"]'), "bid submit")
        submit.click()
        self.page.wait_for_timeout(1500)

    def verified_bid_reference(self) -> str | None:
        new_references = self._all_bid_references() - self.before_bid_references
        if len(new_references) == 1:
            return next(iter(new_references))
        success = self.page.get_by_text("Ставка успешно добавлена", exact=False)
        if success.count() == 1:
            return "submitted"
        return None

    def _all_bid_references(self) -> set[str]:
        hrefs = self.page.locator('a[href*="#bid-"]').evaluate_all(
            "elements => elements.map(element => element.getAttribute('href'))"
        )
        return {reference for href in hrefs if (reference := _bid_reference(href))}


def _unique(locator, name: str):
    count = locator.count()
    if count != 1:
        raise BrowserLayoutError(f"{name} selector matched {count} elements")
    return locator


def _bid_reference(href: str | None) -> str | None:
    if not href or "#bid-" not in href:
        return None
    return href.rsplit("#", 1)[-1]


def run_payload(payload: dict) -> dict:
    from playwright.sync_api import sync_playwright

    request = BrowserBidRequest(**payload["request"])
    profile_dir = Path(payload["profile_dir"])
    artifacts_dir = Path(payload["artifacts_dir"])
    headless = bool(payload.get("headless", True))
    executable_path = payload.get("executable_path") or None
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            executable_path=executable_path,
            viewport={"width": 1440, "height": 1000},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            return execute_bid(
                page=PlaywrightBidPage(page),
                request=request,
                artifacts_dir=artifacts_dir,
                live_submit=bool(payload.get("live_submit")),
            )
        finally:
            context.close()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        result = run_payload(payload)
    except BrowserLayoutError as exc:
        result = {"status": "layout_error", "submitted": False, "error": str(exc)}
    except Exception as exc:
        result = {"status": "worker_error", "submitted": False, "error_type": type(exc).__name__}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"dry_run", "submitted", "already_submitted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
