# Telegram Vacancy Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub Actions based Telegram vacancy monitor that sends suitable AI-assisted freelance opportunities to Daniil.

**Architecture:** A focused Python CLI fetches public Telegram web pages, parses posts, filters them with transparent rules, sends accepted matches to Telegram, and persists seen post IDs in a repository JSON file. GitHub Actions runs the CLI every five minutes and commits state changes.

**Tech Stack:** Python 3.12+, requests, BeautifulSoup4, pytest, GitHub Actions, Telegram Bot API.

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `src/vacancy_monitor/__init__.py`

- [ ] **Step 1: Create packaging and dependency files**

Define a small Python package named `vacancy-monitor`, runtime dependencies `requests` and `beautifulsoup4`, and dev dependency `pytest`.

- [ ] **Step 2: Verify Python can import the empty package**

Run: `PYTHONPATH=src python3 -c "import vacancy_monitor; print(vacancy_monitor.__version__)"`

Expected: prints `0.1.0`.

### Task 2: Filtering and Formatting

**Files:**
- Create: `src/vacancy_monitor/models.py`
- Create: `src/vacancy_monitor/filtering.py`
- Create: `tests/test_filtering.py`

- [ ] **Step 1: Write tests for suitable and unsuitable posts**

Cover an AI-friendly landing-page task, a senior full-time developer vacancy, and a suspicious no-fixed-pay sales post.

- [ ] **Step 2: Implement dataclasses and rule-based filtering**

Create `Post` and `MatchResult`, keyword lists, a scoring function, and Telegram message formatting.

- [ ] **Step 3: Run filtering tests**

Run: `PYTHONPATH=src pytest tests/test_filtering.py -v`

Expected: all tests pass.

### Task 3: Telegram Source Parsing and State

**Files:**
- Create: `src/vacancy_monitor/sources.py`
- Create: `src/vacancy_monitor/state.py`
- Create: `tests/test_sources.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write parsing and state tests**

Use static Telegram-like HTML and temporary JSON files.

- [ ] **Step 2: Implement parser and JSON state store**

Extract message ID, URL, text, date, and source name from `tgme_widget_message` elements.

- [ ] **Step 3: Run parser and state tests**

Run: `PYTHONPATH=src pytest tests/test_sources.py tests/test_state.py -v`

Expected: all tests pass.

### Task 4: CLI and Telegram Sending

**Files:**
- Create: `src/vacancy_monitor/config.py`
- Create: `src/vacancy_monitor/telegram.py`
- Create: `src/vacancy_monitor/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI behavior tests**

Cover first-run seeding without spam and sending only new matching posts.

- [ ] **Step 2: Implement config, sender, and monitor orchestration**

Read environment variables, fetch sources, skip seen IDs, send accepted messages, and save state.

- [ ] **Step 3: Run CLI tests**

Run: `PYTHONPATH=src pytest tests/test_cli.py -v`

Expected: all tests pass.

### Task 5: GitHub Actions and Docs

**Files:**
- Create: `.github/workflows/monitor.yml`
- Create: `README.md`
- Create: `data/.gitkeep`

- [ ] **Step 1: Add scheduled workflow**

Run every five minutes, install dependencies, run monitor, and commit `data/seen_posts.json` when it changes.

- [ ] **Step 2: Document setup**

Explain required GitHub Secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

- [ ] **Step 3: Run full verification**

Run: `python3 -m pip install -r requirements-dev.txt` and `PYTHONPATH=src pytest -v`.

Expected: all tests pass.
