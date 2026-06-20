# Public Project Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Подключить свежие публичные проекты Freelance.ru и Pchel.net, контролировать доступность Kwork/Workzilla и автоматически отправлять первый отклик на явно опубликованный email.

**Architecture:** `public_sources.py` изолирует HTTP/HTML-контракты площадок и возвращает существующие `Post`. `run_monitor` получает еще один тип источников, а `SMTPOutreachClient` подключается к существующему outreach-маршрутизатору; заказы без канала завершаются в `contact_unavailable` без ручных кнопок.

**Tech Stack:** Python 3.12+, requests, BeautifulSoup, smtplib/ssl, email.message, pytest.

---

### Task 1: Парсеры живых публичных проектов

**Files:**
- Create: `src/vacancy_monitor/public_sources.py`
- Create: `tests/test_public_sources.py`

- [x] **Step 1: Write failing parser tests**

Проверить API `parse_freelance_ru(html, fetched_at)` и `parse_pchel(html, fetched_at)` на сокращенных HTML fixtures. Ожидаемые `post_id`: `freelance_ru:3272` и `pchel:1625919`; текст обязан включать заголовок, описание, категорию и бюджет.

- [x] **Step 2: Run RED test**

Run: `PYTHONPATH=src pytest tests/test_public_sources.py -v`

Expected: collection error because `vacancy_monitor.public_sources` does not exist.

- [x] **Step 3: Implement strict parsers**

Создать `SourceContractError`. Freelance.ru читать из `article.task-card`, `.task-card__title-link`, `.task-card__desc`, `.task-card__chips`, `.task-card__budget` и `title` у элемента даты. Pchel читать из `.project-block2`, скрытого `project_id`, `.project-title a`, `.project-text`, `.project-tags` и `.project-athor .price`. Если контейнеры проектов отсутствуют, бросать `SourceContractError`.

- [x] **Step 4: Run GREEN test**

Run: `PYTHONPATH=src pytest tests/test_public_sources.py -v`

Expected: all parser tests pass.

### Task 2: HTTP fetchers and availability probes

**Files:**
- Modify: `src/vacancy_monitor/public_sources.py`
- Modify: `tests/test_public_sources.py`

- [x] **Step 1: Write failing fetch/probe tests**

Проверить реестр `PUBLIC_SOURCE_URLS`, timeout, User-Agent, вызов нужного парсера, Kwork-сигнатуру `<wants-view>` и Workzilla title `Примеры заданий`. Проверить, что probe никогда не возвращает `Post`.

- [x] **Step 2: Run RED test**

Run: `PYTHONPATH=src pytest tests/test_public_sources.py -v`

Expected: missing fetch/probe functions.

- [x] **Step 3: Implement fetch and health records**

Добавить `fetch_public_project_posts(source_name)`, `probe_public_source(source_name)` и immutable `PublicSourceHealth(source, url, checked_at, status, posts, error)`. Не использовать Kwork internal API и Workzilla example payload.

- [x] **Step 4: Run GREEN test**

Run: `PYTHONPATH=src pytest tests/test_public_sources.py -v`

Expected: all source tests pass.

### Task 3: Monitor pipeline and health report

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `src/vacancy_monitor/cli.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_local_agent_cli.py`

- [x] **Step 1: Write failing integration tests**

Проверить defaults `PUBLIC_PROJECT_SOURCES=freelance_ru,pchel` и `PUBLIC_SOURCE_PROBES=kwork,workzilla`; новый подходящий `Post` проходит через `on_match`; ошибка Pchel не блокирует Freelance.ru; JSON health-report содержит записи всех четырех источников.

- [x] **Step 2: Run RED tests**

Run: `PYTHONPATH=src pytest tests/test_config.py tests/test_cli.py tests/test_local_agent_cli.py -v`

Expected: config and monitor do not accept public sources.

- [x] **Step 3: Extend monitor without changing old callers**

Добавить optional `public_project_sources`, `fetch_public_posts` в `run_monitor`. В `run_local_agent_once` обернуть fetch/probe, записать `orders/reports/public_sources_health.json` атомарно и сохранить независимую обработку ошибок.

- [x] **Step 4: Run GREEN tests**

Run: `PYTHONPATH=src pytest tests/test_config.py tests/test_cli.py tests/test_local_agent_cli.py -q`

Expected: integration tests pass.

### Task 4: Email contact and SMTP outreach

**Files:**
- Create: `src/vacancy_monitor/email_outreach.py`
- Create: `tests/test_email_outreach.py`
- Modify: `src/vacancy_monitor/order_models.py`
- Modify: `src/vacancy_monitor/config.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_order_models.py`
- Modify: `tests/test_local_agent_cli.py`

- [x] **Step 1: Write failing contact and SMTP tests**

Проверить извлечение одиночного email из текста `Post`, отсутствие контакта без email, `SMTPOutreachClient.send(order, text)` через TLS/login/send_message, детерминированный Message-ID и статус `contact_unavailable`, когда канала нет.

- [x] **Step 2: Run RED tests**

Run: `PYTHONPATH=src pytest tests/test_email_outreach.py tests/test_order_models.py tests/test_local_agent_cli.py -v`

Expected: missing email client/status behavior.

- [x] **Step 3: Implement channel routing**

Добавить SMTP-поля в `Config`, `OrderStatus.CONTACT_UNAVAILABLE`, email regex в `_contact_from_post`, `SMTPOutreachClient` с `SMTP_SSL` или STARTTLS и маршрутизацию `freelancehunt`/`email`. При отсутствии автоотправляемого контакта переводить `draft_ready` в `contact_unavailable` без Telegram-кнопки.

- [x] **Step 4: Run GREEN tests**

Run: `PYTHONPATH=src pytest tests/test_email_outreach.py tests/test_order_models.py tests/test_local_agent_cli.py -q`

Expected: email and status tests pass.

### Task 5: Documentation, live verification and reload

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`

- [x] **Step 1: Document source and SMTP variables**

Добавить `PUBLIC_PROJECT_SOURCES`, `PUBLIC_SOURCE_PROBES`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL`; описать `contact_unavailable` и ограничения Kwork/Workzilla.

- [x] **Step 2: Run complete verification**

Run: `PYTHONPATH=src pytest -q && python3 -m compileall -q src && git diff --check`

Expected: zero failures and exit code 0.

- [x] **Step 3: Run live source smoke test**

Run a read-only fetch for `freelance_ru` and `pchel`, verify non-empty posts and canonical URLs; run Kwork/Workzilla probes and inspect the health JSON. Do not send outreach during smoke testing.

- [x] **Step 4: Reload local service**

Run: `launchctl kickstart -k gui/$(id -u)/com.codex.vacancy-agent`, then verify `state = running` and empty LaunchAgent stderr.
