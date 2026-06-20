# Autonomous Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Проверять результаты заказа до автосдачи, автоматически исправлять замечания не более двух раз и блокировать некачественную выдачу без ручного согласования.

**Architecture:** Новый модуль `quality.py` выполняет детерминированные проверки и сохраняет структурированные отчеты. `local_agent_cli.py` запускает local+AI review перед отправкой, использует существующий execution client для исправлений и после исчерпания попыток переводит заказ в `quality_failed`.

**Tech Stack:** Python 3.12+, dataclasses, ast/json/csv, OpenAI-compatible Responses API, pytest.

---

### Task 1: Локальный quality checker

**Files:**
- Create: `src/vacancy_monitor/quality.py`
- Create: `tests/test_quality.py`

- [ ] **Step 1: Write failing tests for valid files, empty files, invalid Python/JSON/CSV, leaked secrets and missing README.**
- [ ] **Step 2: Run `PYTHONPATH=src pytest tests/test_quality.py -v` and verify failure because the module is absent.**
- [ ] **Step 3: Implement immutable issue/report types and non-executing file validators using `ast`, `json` and `csv`.**
- [ ] **Step 4: Run `PYTHONPATH=src pytest tests/test_quality.py -v` and verify all local checker tests pass.**

### Task 2: AI quality review and repair contract

**Files:**
- Modify: `src/vacancy_monitor/autopilot.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_autopilot.py`

- [ ] **Step 1: Write failing tests for structured AI review and repair prompts.**
- [ ] **Step 2: Run the focused tests and verify expected missing-method failures.**
- [ ] **Step 3: Add `review_execution_package` and `repair_execution_package` to the OpenAI-compatible client with strict JSON parsing.**
- [ ] **Step 4: Run the focused tests and verify they pass.**

### Task 3: Delivery integration and two repair attempts

**Files:**
- Modify: `src/vacancy_monitor/order_models.py`
- Modify: `src/vacancy_monitor/execution.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_local_agent_cli.py`
- Modify: `tests/test_order_models.py`

- [ ] **Step 1: Write failing integration tests: passed quality sends; failed quality repairs twice; final failure sets `quality_failed`; no approval card is created.**
- [ ] **Step 2: Run the focused tests and verify the failures describe the missing quality gate.**
- [ ] **Step 3: Add replacement package writes, quality report persistence, retry loop and the terminal status.**
- [ ] **Step 4: Run focused tests and verify all scenarios pass.**

### Task 4: Configuration and operating documentation

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`

- [ ] **Step 1: Write failing config tests for autopilot defaults and `AUTO_QUALITY_MAX_REPAIRS=2`.**
- [ ] **Step 2: Implement `AUTO_QUALITY_ENABLED` and bounded repair count configuration.**
- [ ] **Step 3: Document quality reports, failure behavior and environment variables.**
- [ ] **Step 4: Run config tests and verify they pass.**

### Task 5: Verification and live reload

**Files:**
- Verify all changed files and the live service.

- [ ] **Step 1: Run `PYTHONPATH=src pytest -q`.**
- [ ] **Step 2: Run `python3 -m compileall -q src`.**
- [ ] **Step 3: Restart `com.codex.vacancy-agent` with `launchctl kickstart -k`.**
- [ ] **Step 4: Inspect `launchctl print` plus stderr and confirm the process is running without a new traceback.**

