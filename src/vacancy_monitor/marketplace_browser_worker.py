from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vacancy_monitor.marketplace_browser import BrowserConversationRequest, BrowserOutreachRequest, BrowserReplyRequest


@dataclass(frozen=True)
class MarketplaceSelectors:
    login_url: str
    login_markers: tuple[str, ...]
    message: str
    amount: str
    days: str
    submit: str
    conversation: str
    message_rows: str
    message_text: str
    reply: str
    reply_submit: str
    outreach_open_text: str | None = None
    auth_texts: tuple[str, ...] = ()


SELECTORS = {
    "fl_ru": MarketplaceSelectors(
        login_url="https://www.fl.ru/login/",
        login_markers=('a[href*="/login"]',),
        message='textarea[name*="descr"], textarea[name*="message"], textarea',
        amount='input[name*="cost"], input[name*="price"]',
        days='input[name*="days"], input[name*="time"]',
        submit='button[type="submit"], input[type="submit"]',
        conversation='[data-conversation], .b-post-message, .messages, .conversation',
        message_rows='[data-message-id], .message, .b-post-message__item',
        message_text='[data-message-text], .message__text, .b-post-message__text, .text',
        reply='textarea[name*="message"], textarea[name*="text"], textarea',
        reply_submit='button[type="submit"], input[type="submit"]',
        outreach_open_text=None,
        auth_texts=(),
    ),
    "freelance_ru": MarketplaceSelectors(
        login_url="https://freelance.ru/login/",
        login_markers=('a[href*="/login"]',),
        message='textarea[name*="comment"], textarea[name*="message"], textarea',
        amount='input[name*="price"], input[name*="budget"]',
        days='input[name*="days"], input[name*="term"]',
        submit='button[type="submit"], input[type="submit"]',
        conversation='[data-conversation], .messages, .conversation, .dialog-messages',
        message_rows='[data-message-id], .message, .dialog-message',
        message_text='[data-message-text], .message-text, .message__text, .text',
        reply='textarea[name*="message"], textarea[name*="text"], textarea',
        reply_submit='button[type="submit"], input[type="submit"]',
        outreach_open_text=None,
        auth_texts=(),
    ),
    "weblancer": MarketplaceSelectors(
        login_url="https://www.weblancer.net/account/login/",
        login_markers=('a[href*="/account/login"]',),
        message='textarea[name*="description"], textarea[name*="message"], textarea',
        amount='input[name="amount"], input[name*="cost"], input[name*="price"]',
        days='input[name*="days"], input[name*="term"]',
        submit='button[type="button"], button[type="submit"], input[type="submit"]',
        conversation='[data-conversation], .messages, .conversation, .chat',
        message_rows='[data-message-id], .message, .chat-message',
        message_text='[data-message-text], .message-text, .message__text, .text',
        reply='textarea[name*="message"], textarea[name*="text"], textarea',
        reply_submit='button[type="submit"], input[type="submit"]',
        outreach_open_text="Добавить заявку",
        auth_texts=("Авторизуйтесь для подачи заявки",),
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
        self.reply_form = None

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    def auth_required(self) -> bool:
        if any(marker in self.page.url for marker in ("/login", "/signin", "/auth")):
            return True
        if any(self.page.locator(selector).count() > 0 for selector in self.selectors.login_markers):
            return True
        return any(self.page.get_by_text(text, exact=False).count() > 0 for text in self.selectors.auth_texts)

    def captcha_required(self) -> bool:
        title = self.page.title().strip().lower()
        if "__cf_chl_" in self.page.url or title == "just a moment..." or title.startswith("один момент"):
            return True
        return self.page.locator(self.CAPTCHA_SELECTOR).count() > 0

    def fill(self, request: BrowserOutreachRequest) -> None:
        message_locator = self.page.locator(self.selectors.message)
        if message_locator.count() == 0 and self.selectors.outreach_open_text:
            opener = _unique(
                self.page.get_by_role("button", name=self.selectors.outreach_open_text),
                "outreach open",
            )
            opener.click()
            self.page.wait_for_timeout(250)
            message_locator = self.page.locator(self.selectors.message)
        message = _unique(message_locator, "outreach message")
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

    def messages(self) -> list[dict]:
        conversation = _unique(self.page.locator(self.selectors.conversation), "conversation")
        rows = conversation.locator(self.selectors.message_rows)
        messages = []
        for index in range(rows.count()):
            row = rows.nth(index)
            text_locator = _unique(row.locator(self.selectors.message_text), "message text")
            text = text_locator.inner_text().strip()
            if not text:
                continue
            class_name = (row.get_attribute("class") or "").lower()
            author = "self" if any(marker in class_name for marker in ("outgoing", "own", "mine")) else "customer"
            time_locator = row.locator("time")
            created_at = time_locator.first.get_attribute("datetime") if time_locator.count() else None
            messages.append(
                {
                    "message_id": row.get_attribute("data-message-id"),
                    "author": author,
                    "text": text,
                    "created_at": created_at,
                }
            )
        return messages

    def fill_reply(self, request: BrowserReplyRequest) -> None:
        reply = _unique(self.page.locator(self.selectors.reply), "reply message")
        self.reply_form = reply.locator("xpath=ancestor::form[1]")
        if self.reply_form.count() != 1:
            raise BrowserLayoutError("reply form not found")
        reply.fill(request.message)

    def submit_reply(self) -> None:
        if self.reply_form is None:
            raise BrowserLayoutError("reply form was not prepared")
        _unique(self.reply_form.locator(self.selectors.reply_submit), "reply submit").click()
        self.page.wait_for_timeout(1500)

    def reply_reference(self) -> str | None:
        success = self.page.get_by_text(re.compile(r"сообщение.*отправ|ответ.*добав", re.IGNORECASE))
        return "submitted" if success.count() == 1 else None


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


def execute_list_messages(
    *,
    page: OutreachPage,
    request: BrowserConversationRequest,
    artifacts_dir: Path,
) -> dict:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    page.open(request.project_url)
    blocked = _browser_block_result(page=page, artifacts_dir=artifacts_dir, order_id=request.order_id)
    if blocked:
        return blocked
    messages = page.messages()
    page.screenshot(artifacts_dir / "browser_conversation.png")
    return {"status": "messages_read", "order_id": request.order_id, "messages": messages}


def execute_reply(
    *,
    page: OutreachPage,
    request: BrowserReplyRequest,
    artifacts_dir: Path,
    live_submit: bool,
) -> dict:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    page.open(request.project_url)
    blocked = _browser_block_result(page=page, artifacts_dir=artifacts_dir, order_id=request.order_id)
    if blocked:
        return blocked
    page.fill_reply(request)
    page.screenshot(artifacts_dir / "browser_reply_before.png")
    if not live_submit:
        return {"status": "reply_dry_run", "submitted": False, "order_id": request.order_id}
    page.submit_reply()
    page.screenshot(artifacts_dir / "browser_reply_after.png")
    reference = page.reply_reference()
    if not reference:
        return {"status": "reply_unverified", "submitted": False, "order_id": request.order_id}
    return {
        "status": "reply_submitted",
        "submitted": True,
        "order_id": request.order_id,
        "reference": reference,
    }


def _browser_block_result(*, page: OutreachPage, artifacts_dir: Path, order_id: str) -> dict | None:
    if page.captcha_required():
        page.screenshot(artifacts_dir / "browser_captcha.png")
        return {"status": "captcha_required", "submitted": False, "order_id": order_id}
    if page.auth_required():
        page.screenshot(artifacts_dir / "browser_auth_required.png")
        return {"status": "auth_required", "submitted": False, "order_id": order_id}
    return None


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

    operation = payload.get("operation", "submit_outreach")
    request_types = {
        "submit_outreach": BrowserOutreachRequest,
        "list_messages": BrowserConversationRequest,
        "send_reply": BrowserReplyRequest,
    }
    try:
        request = request_types[operation](**payload["request"])
    except KeyError as exc:
        raise ValueError(f"unsupported browser operation: {operation}") from exc
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
            browser_page = PlaywrightOutreachPage(page, selectors)
            artifacts_dir = Path(payload["artifacts_dir"])
            if operation == "list_messages":
                return execute_list_messages(page=browser_page, request=request, artifacts_dir=artifacts_dir)
            if operation == "send_reply":
                return execute_reply(
                    page=browser_page,
                    request=request,
                    artifacts_dir=artifacts_dir,
                    live_submit=bool(payload.get("live_submit", False)),
                )
            return execute_outreach(
                page=browser_page,
                request=request,
                artifacts_dir=artifacts_dir,
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
    return 0 if result.get("status") in {"dry_run", "submitted", "messages_read", "reply_dry_run", "reply_submitted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
