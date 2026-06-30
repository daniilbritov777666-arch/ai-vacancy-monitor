# Freelancehunt Browser Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить локальный браузерный канал, который после однократной авторизации подает безопасные ставки на подходящие разовые проекты Freelancehunt без отключенного API создания ставок.

**Architecture:** Существующий API остается источником проектов, профиля, preflight и переписки. Новый `FreelancehuntBrowserClient` принимает уже проверенный заказ и запускает изолированный Playwright worker с постоянным профилем браузера. Worker сначала работает в dry-run, не обходит CAPTCHA/2FA, а в live-режиме отправляет форму только один раз и возвращает проверяемый JSON-результат.

**Tech Stack:** Python 3.14, Playwright for Python, Chromium persistent context, pytest, JSON order artifacts, macOS LaunchAgent.

---

### Task 1: Browser submission contract

**Files:**
- Create: `src/vacancy_monitor/freelancehunt_browser.py`
- Test: `tests/test_freelancehunt_browser.py`

- [ ] Write failing tests for successful submission, dry-run, unauthenticated session, CAPTCHA and duplicate bid.
- [ ] Run `PYTHONPATH=src pytest -q tests/test_freelancehunt_browser.py` and confirm module/behavior failures.
- [ ] Implement `BrowserBidRequest`, `BrowserBidResult`, `FreelancehuntBrowserClient` and typed errors.
- [ ] Make client write no credentials and return only non-sensitive status fields.
- [ ] Run the focused tests and commit.

### Task 2: Playwright worker

**Files:**
- Create: `src/vacancy_monitor/freelancehunt_browser_worker.py`
- Create: `tests/fixtures/freelancehunt_bid_form.html`
- Test: `tests/test_freelancehunt_browser_worker.py`
- Modify: `requirements.txt`

- [ ] Write failing fixture-based tests for authentication detection, form discovery, value preparation and success detection.
- [ ] Add `playwright>=1.53` and implement a persistent Chromium context under a configurable local profile directory.
- [ ] Use stable form labels/data attributes with explicit fallback selectors; never solve or bypass CAPTCHA.
- [ ] In dry-run, inspect and screenshot without clicking submit.
- [ ] In live mode, click once, wait for an authoritative success state and save before/after screenshots.
- [ ] Run focused tests and commit.

### Task 3: Agent integration and safety gates

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `src/vacancy_monitor/marketplace_planner.py`
- Modify: `scripts/run_local_agent.sh`
- Test: `tests/test_config.py`
- Test: `tests/test_local_agent_cli.py`
- Test: `tests/test_marketplace_planner.py`

- [ ] Write failing tests for `FREELANCEHUNT_BROWSER_ENABLED`, profile path, executable path, timeout and live-submit flag.
- [ ] Write failing tests proving browser submission is selected when the bid API is disabled, but email submission is unchanged.
- [ ] Preserve existing price, age, risk, daily-limit and API preflight checks before browser launch.
- [ ] Record `outbox/freelancehunt_browser_result.json`; map unauthenticated/CAPTCHA/layout errors to retryable channel blockers, not false success.
- [ ] Run focused tests and commit.

### Task 4: Login bootstrap and live dry-run

**Files:**
- Create: `scripts/setup_freelancehunt_browser.sh`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`

- [ ] Add a setup command that installs Chromium and opens a headed persistent profile only for user authentication.
- [ ] Verify profile data stays under `~/.codex/` and is excluded from git.
- [ ] Run dry-run against one currently open, API-preflight-eligible project; do not submit.
- [ ] Save the dry-run result in the matching order directory and commit documentation.

### Task 5: Live deployment

**Files:**
- Modify: `~/Library/LaunchAgents/com.codex.vacancy-agent.plist` during deployment only.

- [ ] Run `PYTHONPATH=src pytest -q` and `python3 -m compileall -q src`.
- [ ] Push the feature branch and fast-forward the live checkout after review.
- [ ] Enable browser mode with API bid mode still disabled.
- [ ] Restart LaunchAgent and verify PID, environment, health reports and stderr.
- [ ] Submit at most one preflight-approved low-risk bid and verify it appears in Freelancehunt UI/API before enabling the normal daily limit.
