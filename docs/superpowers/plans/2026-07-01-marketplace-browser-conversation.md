# Marketplace Browser Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add idempotent reading and safe replying for order-linked conversations on FL.ru, Freelance.ru, and Weblancer.

**Architecture:** Extend the existing isolated Playwright subprocess protocol instead of exposing browser objects to the main agent. Normalize marketplace messages into typed records, persist them through a focused conversation module, and reuse the existing AI intent and reply safety pipeline from the local agent.

**Tech Stack:** Python 3.14, dataclasses, Playwright, repo-local JSON/Markdown state, pytest, macOS LaunchAgent.

---

## File Map

- Modify `src/vacancy_monitor/marketplace_browser.py`: typed message/reply requests and client operations.
- Modify `src/vacancy_monitor/marketplace_browser_worker.py`: conversation selectors, extraction, reply submission, screenshots.
- Create `src/vacancy_monitor/marketplace_conversation.py`: normalized messages, deduplication, inbox files, journal and sent records.
- Modify `src/vacancy_monitor/config.py`: polling and live-reply controls.
- Modify `src/vacancy_monitor/local_agent_cli.py`: linked-order polling, AI reply pipeline, failure isolation.
- Modify `src/vacancy_monitor/marketplace_planner.py`: truthful browser conversation readiness.
- Create `tests/test_marketplace_conversation.py`: persistence and deduplication tests.
- Modify browser, config, planner, and local-agent tests for integration behavior.

### Task 1: Typed Browser Conversation Protocol

**Files:**
- Modify: `src/vacancy_monitor/marketplace_browser.py`
- Test: `tests/test_marketplace_browser.py`

- [ ] **Step 1: Write failing client protocol tests**

Add tests constructing `BrowserConversationRequest(order_id, channel, project_url)` and `BrowserReplyRequest(order_id, channel, project_url, message)` and assert `MarketplaceBrowserClient.list_messages()` and `.send_reply()` invoke the worker with operations `list_messages` and `send_reply`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_browser.py`

Expected: imports or methods fail because the protocol does not exist.

- [ ] **Step 3: Implement minimal protocol**

Add frozen dataclasses and refactor subprocess invocation into:

```python
def _run(self, operation: str, request: object, *, artifacts_dir: Path) -> dict:
    payload = {
        "operation": operation,
        "request": asdict(request),
        "profile_dir": str(self.profile_dir),
        "artifacts_dir": str(artifacts_dir),
        "executable_path": self.executable_path,
        "headless": self.headless,
        "live_submit": self.live_submit,
    }
    return self._invoke(payload)
```

Keep `submit()` backward compatible by routing its request and artifacts directory through `_run("submit_outreach", request, artifacts_dir=artifacts_dir)`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_browser.py`

Commit: `feat: add browser conversation protocol`

### Task 2: Message Extraction And Verified Reply Worker

**Files:**
- Modify: `src/vacancy_monitor/marketplace_browser_worker.py`
- Test: `tests/test_marketplace_browser_worker.py`

- [ ] **Step 1: Write failing worker tests**

Cover normalized output:

```python
assert result == {
    "status": "messages_read",
    "order_id": "order-1",
    "messages": [{"message_id": "m-7", "author": "customer", "text": "Когда начнете?", "created_at": None}],
}
```

Also test auth, CAPTCHA, zero/ambiguous conversation containers, dry-run reply, verified live reply, and missing confirmation.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_browser_worker.py`

Expected: conversation operations and selectors are missing.

- [ ] **Step 3: Implement provider selectors and operations**

Extend `MarketplaceSelectors` with conversation root, message rows, author/text/id attributes, reply textarea, and reply submit selectors. Add:

Implement `execute_list_messages(page, request, artifacts_dir)` and
`execute_reply(page, request, artifacts_dir, live_submit)` as separate functions returning JSON-serializable dictionaries.

Both operations must run CAPTCHA/auth checks before reading or filling. Reply returns `reply_unverified` unless a single success marker is visible.

- [ ] **Step 4: Route operations and verify GREEN**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_browser_worker.py`

Commit: `feat: add marketplace message browser worker`

### Task 3: Idempotent Conversation Persistence

**Files:**
- Create: `src/vacancy_monitor/marketplace_conversation.py`
- Create: `tests/test_marketplace_conversation.py`

- [ ] **Step 1: Write failing persistence tests**

Define `MarketplaceMessage` and test that `sync_marketplace_messages()` writes `inbox/platform_<hash>.json`, appends customer text once to `conversation.md`, and returns only newly stored messages on repeated calls.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_conversation.py`

Expected: module import fails.

- [ ] **Step 3: Implement normalized storage**

Use marketplace message ID when present; otherwise SHA-256 of channel, order ID, author, text, and timestamp. Write atomically through a temporary file. Add `write_marketplace_reply_draft()` and `write_marketplace_reply_sent_record()` under `outbox/`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_conversation.py`

Commit: `feat: persist marketplace conversations`

### Task 4: Local Agent Polling And Safe Auto-Reply

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_local_agent_cli.py`

- [ ] **Step 1: Write failing config and integration tests**

Add `MARKETPLACE_BROWSER_CONVERSATION_ENABLED`, `MARKETPLACE_BROWSER_REPLY_LIVE`, and `MARKETPLACE_BROWSER_ORDERS_PER_CYCLE`. Test only active `platform_browser` orders are polled, new customer messages reach the existing reply client, risky replies remain drafts, and repeated cycles do not resend.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_config.py tests/test_local_agent_cli.py -k 'browser_conversation or marketplace_reply'`

- [ ] **Step 3: Implement polling pipeline**

Add `_sync_marketplace_browser_conversations()` after outreach processing. Restrict statuses to `OUTREACH_SENT`, `DISCOVERY`, `DRAFT_READY`, `AWAITING_TERMS_APPROVAL`, and `PAYMENT_REQUESTED`; require matching order URL and contact channel. Reuse `classify_customer_messages()` before sending. Persist `browser_conversation_result.json` for every attempt.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused command from Step 2.

Commit: `feat: integrate browser customer conversations`

### Task 5: Readiness Reporting And Safe Rollout

**Files:**
- Modify: `src/vacancy_monitor/marketplace_planner.py`
- Modify: `tests/test_marketplace_planner.py`
- Modify: `.env.example`
- Modify: `scripts/migrate_to_rf_marketplaces.sh`
- Modify: `scripts/run_local_agent.sh`

- [ ] **Step 1: Write failing readiness tests**

Assert dry-run reports `browser_conversation_dry_run`; live mode reports `platform_auto` only when both browser outreach and reply live flags are enabled.

- [ ] **Step 2: Verify RED and implement reporting**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_planner.py`

Add safe production defaults:

```text
MARKETPLACE_BROWSER_CONVERSATION_ENABLED=true
MARKETPLACE_BROWSER_REPLY_LIVE=false
MARKETPLACE_BROWSER_ORDERS_PER_CYCLE=3
```

- [ ] **Step 3: Full verification**

Run: `PYTHONPATH=src pytest -q && python3 -m compileall -q src && git diff --check`

Expected: zero failures and clean static checks.

- [ ] **Step 4: Commit, deploy, and inspect**

Commit: `feat: roll out browser conversations in dry run`

Run migration, reload `com.codex.vacancy-agent`, confirm new environment values, inspect fresh health reports, and verify no reply was submitted while live mode is false.

- [ ] **Step 5: Provider dry-run gate**

For each authenticated provider, run one linked-order message read and reply dry-run. Inspect JSON plus screenshots. Enable live reply per provider only after selectors and order linking are verified.
