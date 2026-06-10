# Autopilot Agent Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OpenAI-backed autopilot layer that can analyze safe one-off IT orders, generate outreach, execution plans, deliverable drafts, and customer messages while respecting hard safety limits and channel constraints.

**Architecture:** Keep the monitor/order-store/workspace flow. Add `autopilot.py` for structured AI results and file generation, extend `Config` with `AUTO_MODE`, model, price limit, and API key, then call autopilot after order creation in local agent mode. If no customer channel exists, write `outbox/customer_message.md` instead of sending externally.

**Tech Stack:** Python 3.12+, requests, pytest, OpenAI Responses API over HTTPS with JSON schema output.

---

### Task 1: Autopilot Config

- [ ] Add tests for `AUTO_MODE`, `AUTO_MAX_PRICE_RUB`, `OPENAI_MODEL`, and missing `OPENAI_API_KEY` behavior.
- [ ] Add config fields and env parsing.
- [ ] Run `PYTHONPATH=src pytest tests/test_config.py -v`.

### Task 2: Structured OpenAI Client

- [ ] Add tests with mocked `requests.post` for `/v1/responses`, JSON schema payload, and parsed output.
- [ ] Implement `OpenAIResponsesClient` without storing API keys.
- [ ] Run `PYTHONPATH=src pytest tests/test_autopilot.py -v`.

### Task 3: Autopilot Files And Safety

- [ ] Add tests for writing `autopilot/analysis.json`, `autopilot/outreach.md`, `autopilot/execution_plan.md`, `deliverables/autopilot_result.md`, and `outbox/customer_message.md`.
- [ ] Add tests that unsafe or over-budget AI results do not move order to `draft_ready`.
- [ ] Implement `run_order_autopilot`.
- [ ] Run `PYTHONPATH=src pytest tests/test_autopilot.py -v`.

### Task 4: Local Agent Integration

- [ ] Add tests that `AUTO_MODE=off` preserves current behavior, `draft` writes files and keeps approval status, and `autopilot` moves safe orders to `draft_ready`.
- [ ] Wire autopilot after order creation.
- [ ] Run affected tests and full suite.

### Task 5: Docs And Runtime

- [ ] Update README with `OPENAI_API_KEY`, `AUTO_MODE`, and current channel limitation.
- [ ] Verify full suite.
- [ ] Restart LaunchAgent only if `OPENAI_API_KEY` is available.
