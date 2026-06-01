# Semi-Autonomous Freelance Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local semi-autonomous freelance agent that creates per-order workspaces, routes all risky actions through Russian Telegram approval buttons, and prepares manual Codex/ChatGPT execution prompts.

**Architecture:** Keep the existing monitor as the source discovery layer and add a local agent layer around persisted orders. The first implementation stores order state in repository JSON files, creates `orders/<order_id>/` workspaces, sends Telegram approval cards, and handles safe status transitions without contacting customers automatically unless a supported channel is later added.

**Tech Stack:** Python 3.12+, stdlib dataclasses/json/pathlib/datetime, requests, pytest, Telegram Bot API.

---

## File Structure

- Create `src/vacancy_monitor/order_models.py`: order dataclasses, status constants, Russian timestamp formatting, stable order ID generation.
- Create `src/vacancy_monitor/order_store.py`: JSON-backed order persistence, atomic writes, index maintenance, status updates.
- Create `src/vacancy_monitor/workspace.py`: `orders/<order_id>/` creation and Russian markdown files.
- Create `src/vacancy_monitor/agent.py`: converts accepted posts into orders, prepares first outreach, creates workspaces, and sends Telegram cards.
- Create `src/vacancy_monitor/telegram_control.py`: Telegram inline keyboard payloads and callback transition handling.
- Create `src/vacancy_monitor/local_agent_cli.py`: local entrypoint that runs one monitor pass in agent mode and can poll Telegram callbacks.
- Modify `src/vacancy_monitor/telegram.py`: add optional `reply_markup`, callback answer helper, and update helper while preserving current `send_telegram_message` behavior.
- Modify `src/vacancy_monitor/config.py`: add local agent paths and polling options.
- Modify `src/vacancy_monitor/cli.py`: let the monitor call an optional match handler so agent mode can create orders instead of only sending notifications.
- Create tests:
  - `tests/test_order_models.py`
  - `tests/test_order_store.py`
  - `tests/test_workspace.py`
  - `tests/test_telegram_control.py`
  - `tests/test_agent.py`
  - `tests/test_local_agent_cli.py`
- Modify `README.md`: document local agent setup and РФ-format behavior.

---

### Task 1: Order Models And РФ Formatting

**Files:**
- Create: `src/vacancy_monitor/order_models.py`
- Create: `tests/test_order_models.py`

- [ ] **Step 1: Write failing tests for statuses, order IDs, and РФ timestamps**

Add this test file:

```python
from datetime import datetime, timezone

from vacancy_monitor.models import Post
from vacancy_monitor.order_models import (
    OrderStatus,
    build_order_id,
    format_moscow_time,
    make_order_from_post,
)


def test_format_moscow_time_uses_ru_format():
    value = datetime(2026, 6, 1, 9, 5, tzinfo=timezone.utc)

    assert format_moscow_time(value) == "01.06.2026 12:05 МСК"


def test_build_order_id_is_stable_and_filesystem_safe():
    post = Post(
        source="freelancehunt.com/projects.rss",
        post_id="freelancehunt.com/projects.rss:https://example.com/project?id=42",
        url="https://example.com/project?id=42",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    order_id = build_order_id(post)

    assert order_id.startswith("20260601-")
    assert "/" not in order_id
    assert "?" not in order_id


def test_make_order_from_post_uses_ru_defaults():
    post = Post(
        source="sample",
        post_id="sample/10",
        url="https://t.me/sample/10",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    order = make_order_from_post(post, category="Telegram-боты", risks=["уточнить доступы"])

    assert order.status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert order.category == "Telegram-боты"
    assert order.price_rub is None
    assert order.deadline_ru is None
    assert order.risks == ["уточнить доступы"]
    assert order.created_at.endswith("МСК")
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `PYTHONPATH=src pytest tests/test_order_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'vacancy_monitor.order_models'`.

- [ ] **Step 3: Implement order models**

Create `src/vacancy_monitor/order_models.py` with these public names and behavior:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from vacancy_monitor.models import Post

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class OrderStatus(StrEnum):
    NEW = "new"
    AWAITING_RESPONSE_APPROVAL = "awaiting_response_approval"
    OUTREACH_SENT = "outreach_sent"
    MANUAL_SEND_NEEDED = "manual_send_needed"
    SEND_FAILED = "send_failed"
    DISCOVERY = "discovery"
    AWAITING_TERMS_APPROVAL = "awaiting_terms_approval"
    DRAFT_READY = "draft_ready"
    AWAITING_DELIVERY_APPROVAL = "awaiting_delivery_approval"
    PAYMENT_REQUESTED = "payment_requested"
    CLOSED = "closed"


@dataclass(frozen=True)
class CustomerContact:
    channel: str
    value: str
    can_auto_send: bool = False


@dataclass(frozen=True)
class Order:
    order_id: str
    source: str
    source_url: str
    original_post_id: str
    original_text: str
    category: str
    status: OrderStatus
    created_at: str
    updated_at: str
    contact: CustomerContact | None = None
    latest_approved_outreach: str | None = None
    price_rub: int | None = None
    deadline_ru: str | None = None
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        contact_data = data.get("contact")
        contact = CustomerContact(**contact_data) if contact_data else None
        return cls(
            order_id=data["order_id"],
            source=data["source"],
            source_url=data["source_url"],
            original_post_id=data["original_post_id"],
            original_text=data["original_text"],
            category=data["category"],
            status=OrderStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            contact=contact,
            latest_approved_outreach=data.get("latest_approved_outreach"),
            price_rub=data.get("price_rub"),
            deadline_ru=data.get("deadline_ru"),
            risks=list(data.get("risks", [])),
        )
```

Also implement:

```python
def format_moscow_time(value: datetime | None = None) -> str:
    current = value or datetime.now(tz=UTC)
    return current.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")


def build_order_id(post: Post) -> str:
    published = _parse_post_datetime(post.published_at)
    date_prefix = published.astimezone(MOSCOW_TZ).strftime("%Y%m%d")
    digest = hashlib.sha1(post.post_id.encode("utf-8")).hexdigest()[:10]
    source_slug = re.sub(r"[^a-zA-Z0-9]+", "-", post.source).strip("-").lower() or "source"
    return f"{date_prefix}-{source_slug}-{digest}"


def make_order_from_post(post: Post, *, category: str, risks: list[str] | None = None) -> Order:
    now_ru = format_moscow_time()
    return Order(
        order_id=build_order_id(post),
        source=post.source,
        source_url=post.url,
        original_post_id=post.post_id,
        original_text=post.text,
        category=category,
        status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        created_at=now_ru,
        updated_at=now_ru,
        risks=risks or [],
    )


def _parse_post_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
```

- [ ] **Step 4: Run model tests**

Run: `PYTHONPATH=src pytest tests/test_order_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/order_models.py tests/test_order_models.py
git commit -m "feat: add order models"
```

---

### Task 2: JSON Order Store

**Files:**
- Create: `src/vacancy_monitor/order_store.py`
- Create: `tests/test_order_store.py`

- [ ] **Step 1: Write failing tests for persistence and index rebuild**

Add tests that create an order, save it under a temporary `orders/` directory, load it back, update status, and rebuild the index from per-order `state.json`.

Use these assertions:

```python
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.models import Post


def make_post() -> Post:
    return Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )


def test_save_order_writes_state_and_index(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])

    store.save_order(order)

    assert (tmp_path / "orders" / order.order_id / "state.json").exists()
    index = store.load_index()
    assert index["orders"][0]["order_id"] == order.order_id
    assert index["orders"][0]["status"] == OrderStatus.AWAITING_RESPONSE_APPROVAL.value


def test_update_status_persists_order_and_index(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)

    updated = store.update_status(order.order_id, OrderStatus.MANUAL_SEND_NEEDED)

    assert updated.status == OrderStatus.MANUAL_SEND_NEEDED
    assert store.load_order(order.order_id).status == OrderStatus.MANUAL_SEND_NEEDED
    assert store.load_index()["orders"][0]["status"] == "manual_send_needed"


def test_rebuild_index_uses_state_files_as_source_of_truth(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order_from_post(make_post(), category="Telegram-боты", risks=[])
    store.save_order(order)
    (tmp_path / "orders" / "index.json").write_text('{"orders": []}\n', encoding="utf-8")

    rebuilt = store.rebuild_index()

    assert rebuilt["orders"][0]["order_id"] == order.order_id
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_order_store.py -v`

Expected: FAIL with missing `vacancy_monitor.order_store`.

- [ ] **Step 3: Implement JSON store with atomic writes**

Create `OrderStore` with:

```python
class OrderStore:
    def __init__(self, orders_dir: Path):
        self.orders_dir = orders_dir
        self.index_path = orders_dir / "index.json"

    def order_dir(self, order_id: str) -> Path:
        return self.orders_dir / order_id

    def state_path(self, order_id: str) -> Path:
        return self.order_dir(order_id) / "state.json"

    def save_order(self, order: Order) -> None:
        self.order_dir(order.order_id).mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.state_path(order.order_id), order.to_dict())
        self._upsert_index(order)

    def load_order(self, order_id: str) -> Order:
        return Order.from_dict(_read_json(self.state_path(order_id)))

    def load_index(self) -> dict:
        if not self.index_path.exists():
            return {"orders": []}
        return _read_json(self.index_path)

    def update_status(self, order_id: str, status: OrderStatus) -> Order:
        order = self.load_order(order_id)
        updated = replace(order, status=status, updated_at=format_moscow_time())
        self.save_order(updated)
        return updated

    def rebuild_index(self) -> dict:
        orders = [Order.from_dict(_read_json(path)) for path in self.orders_dir.glob("*/state.json")]
        index = {"orders": [_index_entry(order) for order in sorted(orders, key=lambda item: item.created_at)]}
        _write_json_atomic(self.index_path, index)
        return index
```

Implement helpers `_read_json`, `_write_json_atomic`, `_index_entry`, and `_upsert_index`. `_write_json_atomic` must write to `path.with_suffix(path.suffix + ".tmp")` and then replace the target path.

- [ ] **Step 4: Run store tests**

Run: `PYTHONPATH=src pytest tests/test_order_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/order_store.py tests/test_order_store.py
git commit -m "feat: add json order store"
```

---

### Task 3: Per-Order Workspace Files

**Files:**
- Create: `src/vacancy_monitor/workspace.py`
- Create: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests for РФ workspace files**

Test that creating a workspace writes:

- `brief.md`;
- `conversation.md`;
- `prompt.md`;
- `deliverables/`.

Assertions:

```python
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post
from vacancy_monitor.workspace import create_order_workspace


def test_create_order_workspace_writes_ru_files(tmp_path):
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    order = make_order_from_post(post, category="Telegram-боты", risks=["уточнить доступы"])

    create_order_workspace(tmp_path / "orders", order)

    order_dir = tmp_path / "orders" / order.order_id
    assert "Исходный заказ" in (order_dir / "brief.md").read_text(encoding="utf-8")
    assert "История переписки" in (order_dir / "conversation.md").read_text(encoding="utf-8")
    assert "Задача для Codex/ChatGPT" in (order_dir / "prompt.md").read_text(encoding="utf-8")
    assert (order_dir / "deliverables").is_dir()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_workspace.py -v`

Expected: FAIL with missing `vacancy_monitor.workspace`.

- [ ] **Step 3: Implement workspace creation**

Implement `create_order_workspace(orders_dir: Path, order: Order) -> Path` that creates files only when they do not exist, so later manual edits are not overwritten.

Use Russian templates:

```markdown
# Заказ <order_id>

## Исходный заказ

Источник: <source>
Ссылка: <source_url>
Категория: <category>

## Текст

<original_text>

## Риски

- <risk>
```

`prompt.md` must include:

```markdown
# Задача для Codex/ChatGPT

Ты помогаешь выполнить фриланс-заказ в РФ-формате. Ответы и документы готовь на русском языке. Суммы указывай в рублях, даты в формате ДД.ММ.ГГГГ.
```

- [ ] **Step 4: Run workspace tests**

Run: `PYTHONPATH=src pytest tests/test_workspace.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/workspace.py tests/test_workspace.py
git commit -m "feat: create order workspaces"
```

---

### Task 4: Telegram Control Buttons And Safe Transitions

**Files:**
- Create: `src/vacancy_monitor/telegram_control.py`
- Create: `tests/test_telegram_control.py`

- [ ] **Step 1: Write failing tests for callback payloads and safety gates**

Test:

- callback payload is compact and includes action + order ID;
- `approve_outreach` from `awaiting_response_approval` moves to `manual_send_needed` for manual mode;
- `approve_terms` is rejected unless status is `awaiting_terms_approval`;
- stale callbacks do not mutate state.

Example assertion:

```python
from vacancy_monitor.order_models import OrderStatus
from vacancy_monitor.telegram_control import (
    CallbackAction,
    build_order_keyboard,
    parse_callback_data,
    resolve_transition,
)


def test_parse_callback_data():
    parsed = parse_callback_data("order:approve_outreach:abc123")

    assert parsed.action == CallbackAction.APPROVE_OUTREACH
    assert parsed.order_id == "abc123"


def test_approve_outreach_requires_waiting_status():
    next_status = resolve_transition(
        action=CallbackAction.APPROVE_OUTREACH,
        current_status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        can_auto_send=False,
    )

    assert next_status == OrderStatus.MANUAL_SEND_NEEDED


def test_approve_terms_rejects_stale_status():
    next_status = resolve_transition(
        action=CallbackAction.APPROVE_TERMS,
        current_status=OrderStatus.AWAITING_RESPONSE_APPROVAL,
        can_auto_send=False,
    )

    assert next_status is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_telegram_control.py -v`

Expected: FAIL with missing `vacancy_monitor.telegram_control`.

- [ ] **Step 3: Implement callback actions**

Create:

```python
class CallbackAction(StrEnum):
    APPROVE_OUTREACH = "approve_outreach"
    EDIT = "edit"
    REJECT = "reject"
    SENT_MANUALLY = "sent_manually"
    APPROVE_TERMS = "approve_terms"
    REQUEST_CHANGES = "request_changes"
    DRAFT_READY = "draft_ready"
    ALLOW_SENDING = "allow_sending"
    PAYMENT_NEEDED = "payment_needed"
    CLOSE = "close"
```

Implement `build_order_keyboard(order: Order) -> dict` returning Telegram `inline_keyboard` with Russian button text:

```python
{"text": "Одобрить отклик", "callback_data": f"order:approve_outreach:{order.order_id}"}
```

Implement `resolve_transition(...)` with explicit allowed transitions:

- `approve_outreach` from `awaiting_response_approval` to `outreach_sent` when `can_auto_send=True`;
- `approve_outreach` from `awaiting_response_approval` to `manual_send_needed` when `can_auto_send=False`;
- `sent_manually` from `manual_send_needed` to `discovery`;
- `approve_terms` from `awaiting_terms_approval` to `draft_ready`;
- `draft_ready` from `draft_ready` to `awaiting_delivery_approval`;
- `allow_sending` from `awaiting_delivery_approval` to `payment_requested`;
- `payment_needed` from `awaiting_delivery_approval` or `payment_requested` to `payment_requested`;
- `close` from any status to `closed`;
- unsupported combinations return `None`.

- [ ] **Step 4: Run Telegram control tests**

Run: `PYTHONPATH=src pytest tests/test_telegram_control.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/telegram_control.py tests/test_telegram_control.py
git commit -m "feat: add telegram approval transitions"
```

---

### Task 5: Telegram API Helpers

**Files:**
- Modify: `src/vacancy_monitor/telegram.py`
- Create: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests for reply markup and callback answers**

Use monkeypatch to replace `requests.post` and verify:

- existing simple send still works;
- optional `reply_markup` is included;
- `answer_callback_query` calls Telegram API with callback ID.

Expected test names:

```python
def test_send_telegram_message_supports_reply_markup(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("vacancy_monitor.telegram.requests.post", fake_post)

    send_telegram_message(
        "token",
        "150761046",
        "Привет",
        reply_markup={"inline_keyboard": [[{"text": "Одобрить отклик", "callback_data": "order:approve_outreach:abc"}]]},
    )

    assert calls[0]["json"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Одобрить отклик"

def test_answer_callback_query_posts_to_api(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("vacancy_monitor.telegram.requests.post", fake_post)

    answer_callback_query("token", "callback-1", "Готово.")

    assert calls[0]["url"].endswith("/answerCallbackQuery")
    assert calls[0]["json"]["callback_query_id"] == "callback-1"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_telegram.py -v`

Expected: FAIL because `send_telegram_message` does not accept `reply_markup` and `answer_callback_query` does not exist.

- [ ] **Step 3: Extend Telegram helpers without breaking current callers**

Change signature to:

```python
def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> None:
```

Build payload with `chat_id`, `text[:4000]`, `disable_web_page_preview=True`, and optional `reply_markup`.

Add:

```python
def answer_callback_query(bot_token: str, callback_query_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text[:200], "show_alert": False},
        timeout=20,
    )
    response.raise_for_status()
```

- [ ] **Step 4: Run Telegram tests and current CLI tests**

Run: `PYTHONPATH=src pytest tests/test_telegram.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/telegram.py tests/test_telegram.py
git commit -m "feat: support telegram approval markup"
```

---

### Task 6: Agent Order Creation From Matched Posts

**Files:**
- Create: `src/vacancy_monitor/agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests for creating an order from a matched post**

Test that a matched post:

- creates `state.json`;
- creates workspace files;
- sends a Telegram card with Russian text;
- includes inline buttons;
- does not mark anything as customer-sent.

Key test shape:

```python
from vacancy_monitor.agent import handle_matched_post
from vacancy_monitor.models import MatchResult, Post
from vacancy_monitor.order_store import OrderStore


def test_handle_matched_post_creates_order_and_sends_approval_card(tmp_path):
    sent = []
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )
    result = MatchResult(accepted=True, score=3, reasons=["боты", "есть сигнал оплаты"], risks=[])

    order = handle_matched_post(
        post=post,
        result=result,
        store=OrderStore(tmp_path / "orders"),
        send_approval=lambda text, reply_markup: sent.append((text, reply_markup)),
    )

    assert order.status.value == "awaiting_response_approval"
    assert (tmp_path / "orders" / order.order_id / "state.json").exists()
    assert (tmp_path / "orders" / order.order_id / "prompt.md").exists()
    assert "Одобрить отклик" in str(sent[0][1])
    assert "Первый отклик" in sent[0][0]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_agent.py -v`

Expected: FAIL with missing `vacancy_monitor.agent`.

- [ ] **Step 3: Implement agent handler**

Implement:

```python
def handle_matched_post(
    *,
    post: Post,
    result: MatchResult,
    store: OrderStore,
    send_approval: Callable[[str, dict], None],
) -> Order:
```

Behavior:

- infer category from `result.reasons` using Russian labels;
- create `Order` with `make_order_from_post`;
- `store.save_order(order)`;
- `create_order_workspace(store.orders_dir, order)`;
- build a Russian first outreach draft;
- send Telegram card with `build_order_keyboard(order)`;
- return the order.

First outreach draft must be conservative:

```text
Здравствуйте! Готов обсудить задачу. Могу быстро уточнить ТЗ, предложить понятный план и выполнить работу фиксированным этапом. Подскажите, пожалуйста, какой дедлайн и какой бюджет заложен?
```

- [ ] **Step 4: Run agent tests**

Run: `PYTHONPATH=src pytest tests/test_agent.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/agent.py tests/test_agent.py
git commit -m "feat: create orders from matched posts"
```

---

### Task 7: Wire Agent Mode Into Monitor Flow

**Files:**
- Modify: `src/vacancy_monitor/cli.py`
- Create: `tests/test_local_agent_cli.py`
- Create: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `src/vacancy_monitor/config.py`

- [ ] **Step 1: Write tests for local agent mode**

Test that local agent mode:

- calls existing fetchers;
- creates an order for a matched post;
- sends an approval card instead of the old "Подходит" notification;
- keeps first-run seeding behavior.

Expected command-level test:

```python
def test_run_local_agent_creates_order_for_new_match(tmp_path):
    sent = []
    config = Config(
        bot_token="token",
        chat_id="150761046",
        channels=["sample"],
        rss_feeds=[],
        state_path=tmp_path / "seen_posts.json",
        send_first_run=True,
        orders_path=tmp_path / "orders",
    )
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://t.me/sample/1",
        text="Нужен Telegram-бот для заявок, бюджет 15 000 руб.",
        published_at="2026-06-01T12:00:00+03:00",
    )

    summary = run_local_agent_once(
        config,
        fetch_posts=lambda channel: [post],
        fetch_rss_posts=lambda feed: [],
        send_message=lambda text, reply_markup=None: sent.append((text, reply_markup)),
    )

    assert summary.sent == 1
    assert list((tmp_path / "orders").glob("*/state.json"))
    assert "Первый отклик" in sent[0][0]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py -v`

Expected: FAIL because `local_agent_cli` does not exist.

- [ ] **Step 3: Add match handler to monitor orchestration**

Modify `run_monitor` so it accepts an optional callback:

```python
on_match: Callable[[Post, MatchResult], None] | None = None
```

When a post is accepted:

- if `on_match` is set, call `on_match(post, result)`;
- otherwise preserve existing behavior and send the formatted notification.

Keep the state save behavior unchanged.

- [ ] **Step 4: Implement local agent entrypoint**

Create `local_agent_cli.py` with:

```python
def run_local_agent_once(config: Config) -> MonitorSummary:
    store = OrderStore(config.orders_path)

    def on_match(post: Post, result: MatchResult) -> None:
        handle_matched_post(
            post=post,
            result=result,
            store=store,
            send_approval=lambda text, reply_markup: send_telegram_message(
                config.bot_token,
                config.chat_id,
                text,
                reply_markup=reply_markup,
            ),
        )

    return run_monitor(
        channels=config.channels,
        rss_feeds=config.rss_feeds,
        state_path=config.state_path,
        fetch_posts=fetch_channel_posts,
        fetch_rss_posts=fetch_rss_feed_posts,
        send_message=lambda text: send_telegram_message(config.bot_token, config.chat_id, text),
        send_first_run=config.send_first_run,
        on_match=on_match,
    )
```

Add `Config.orders_path` defaulting to `Path("orders")` from env `ORDERS_PATH`.

- [ ] **Step 5: Run affected tests**

Run: `PYTHONPATH=src pytest tests/test_cli.py tests/test_local_agent_cli.py tests/test_agent.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vacancy_monitor/cli.py src/vacancy_monitor/config.py src/vacancy_monitor/local_agent_cli.py tests/test_cli.py tests/test_local_agent_cli.py
git commit -m "feat: add local agent monitor mode"
```

---

### Task 8: Callback Handling Command

**Files:**
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Create or extend: `tests/test_local_agent_cli.py`

- [ ] **Step 1: Write tests for applying callback transitions**

Test a function:

```python
def handle_order_callback(
    *,
    callback_data: str,
    store: OrderStore,
    answer: Callable[[str], None],
) -> Order | None:
```

Assert that:

- valid callback updates status;
- invalid callback returns `None`;
- stale callback leaves status unchanged and calls answer with Russian text.

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py::test_handle_order_callback -v`

Expected: FAIL because the function does not exist.

- [ ] **Step 3: Implement callback application**

Implementation must:

- parse callback with `parse_callback_data`;
- load order from store;
- call `resolve_transition`;
- if transition is `None`, call `answer("Действие уже неактуально или недоступно.")` and return `None`;
- update status through `store.update_status`;
- call `answer("Готово.")`;
- return updated order.

- [ ] **Step 4: Run callback tests**

Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/local_agent_cli.py tests/test_local_agent_cli.py
git commit -m "feat: handle order callbacks"
```

---

### Task 9: README And Local Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document local agent usage**

Add a section in Russian:

```markdown
## Локальный полуавтономный агент

Агент запускается на компьютере Даниила и создает папки заказов в `orders/`.

Форматы первой версии:

- язык сообщений и документов: русский;
- даты: `ДД.ММ.ГГГГ HH:MM МСК`;
- суммы: рубли;
- первый отклик, цена, сроки, отправка результата и оплата требуют подтверждения через Telegram.

Запуск одной проверки:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```
```

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src pytest -v`

Expected: PASS.

- [ ] **Step 3: Run import smoke test**

Run:

```bash
PYTHONPATH=src python3 -c "from vacancy_monitor.local_agent_cli import run_local_agent_once; print(run_local_agent_once.__name__)"
```

Expected: prints `run_local_agent_once`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document local freelance agent"
```

---

## Self-Review

Spec coverage:

- Local execution is covered by Task 7 and Task 9.
- JSON order state is covered by Task 2.
- Per-order folders are covered by Task 3.
- Russian/RF formatting is covered by Task 1, Task 3, Task 4, and Task 9.
- Telegram approval buttons are covered by Task 4 and Task 5.
- First-outreach approval and manual send are covered by Task 4, Task 6, and Task 8.
- Manual Codex/ChatGPT execution is covered by Task 3 and Task 6 through `prompt.md`.
- No OpenAI API, no web dashboard, no browser login, and no autonomous payment are preserved because the plan adds no such integration.

Known MVP limitation:

- This plan builds the local order orchestration and approval layer. Actual customer-channel adapters for email, exchange APIs, or Telegram user messaging remain manual-mode only until a later plan adds one supported channel at a time.
