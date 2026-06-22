# Durable Agent Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить локальную транзакционную очередь, чтобы поиск проектов не блокировался AI-вызовами, а временные ошибки автоматически повторялись после перезапуска процесса.

**Architecture:** SQLite хранит только фоновые задания и lease, а существующие `orders/<order_id>/state.json` остаются доменным состоянием. Мониторинг создает заказ и идемпотентный `advance_order`; ограниченный worker обрабатывает очередь после мониторинга и использует текущий autopilot-контур.

**Tech Stack:** Python 3.14, stdlib `sqlite3`, JSON, pytest, macOS LaunchAgent.

---

### Task 1: Транзакционное ядро SQLite-очереди

**Files:**
- Create: `src/vacancy_monitor/job_queue.py`
- Create: `tests/test_job_queue.py`

- [ ] **Step 1: Write failing schema and idempotency tests**

Создать тесты `test_enqueue_is_idempotent`, `test_claim_next_leases_only_one_job`, `test_complete_marks_job_succeeded`. Использовать фиксированное UTC-время через параметр `now` и временную БД `tmp_path / "jobs.sqlite3"`.

Ожидаемый интерфейс:

```python
queue = AgentJobQueue(path)
job = queue.enqueue(
    order_id="order-1",
    kind="advance_order",
    payload={"version": 1},
    idempotency_key="advance_order:order-1",
    max_attempts=4,
    now=NOW,
)
claimed = queue.claim_next(lease_seconds=600, now=NOW)
queue.complete(claimed.job_id, now=NOW)
```

- [ ] **Step 2: Run RED tests**

Run: `PYTHONPATH=src pytest tests/test_job_queue.py -v`

Expected: import error for `vacancy_monitor.job_queue`.

- [ ] **Step 3: Implement queue records and atomic operations**

Добавить `JobStatus(StrEnum)`, immutable `AgentJob`, `AgentJobQueue`. Инициализация создает таблицу `jobs`, unique index по `idempotency_key` и index `(status, available_at)`. `claim_next` выполняет `BEGIN IMMEDIATE`, выбирает старейший доступный `pending`, увеличивает `attempts`, ставит `leased` и `lease_until`.

- [ ] **Step 4: Add retry, dead-letter and lease recovery tests**

Проверить:

```python
queue.retry(job_id, RuntimeError("temporary"), delay_seconds=60, now=NOW)
assert queue.get(job_id).status == JobStatus.PENDING
assert queue.claim_next(now=NOW) is None
assert queue.claim_next(now=NOW + timedelta(seconds=60)) is not None

queue.fail(job_id, ValueError("invalid"), now=NOW)
assert queue.get(job_id).status == JobStatus.DEAD

assert queue.release_expired_leases(now=NOW + timedelta(minutes=11)) == 1
```

- [ ] **Step 5: Run GREEN tests**

Run: `PYTHONPATH=src pytest tests/test_job_queue.py -q`

Expected: all queue tests pass.

### Task 2: Конфигурация, классификация ошибок и наблюдаемость

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Create: `src/vacancy_monitor/job_worker.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_job_worker.py`

- [ ] **Step 1: Write failing config tests**

Проверить defaults и env override:

```python
assert config.agent_queue_enabled is True  # AUTO_MODE=autopilot
assert config.agent_jobs_per_cycle == 3
assert config.agent_job_max_attempts == 4
assert config.agent_job_lease_seconds == 600
assert config.agent_queue_path == config.orders_path / "agent_jobs.sqlite3"
```

Явный `AGENT_QUEUE_ENABLED=false` должен выключать очередь. `AGENT_JOB_MAX_ATTEMPTS` ограничить диапазоном `1..8`, jobs per cycle `1..20`, lease `30..3600`.

- [ ] **Step 2: Implement config fields**

Добавить поля `agent_queue_enabled`, `agent_queue_path`, `agent_jobs_per_cycle`, `agent_job_max_attempts`, `agent_job_lease_seconds`. Путь по умолчанию вычислять после `ORDERS_PATH`, а boolean наследовать от `AUTO_MODE=autopilot`.

- [ ] **Step 3: Write failing retry-classification tests**

`is_retryable_job_error(exc)` возвращает true для `requests.Timeout`, `requests.ConnectionError`, HTTP `408`, `429`, `500..599`; false для `ValueError`, HTTP `400`, `401`, `403`, `404`, `410`, `422`.

`retry_delay_seconds(attempts, job_id)` возвращает детерминированные задержки на базе `60`, `300`, `900` секунд с jitter не больше 10%.

- [ ] **Step 4: Implement worker helpers and atomic reports**

В `job_worker.py` добавить классификацию, delay, `write_job_attempt(...)`, `write_dead_letter(...)`, `write_queue_health(...)`. Ошибки сохранять как тип, HTTP status и строку до 200 символов; заголовки, ключи и response body не писать.

- [ ] **Step 5: Run task tests**

Run: `PYTHONPATH=src pytest tests/test_config.py tests/test_job_worker.py -q`

Expected: all config and worker helper tests pass.

### Task 3: Producer, reconciler и worker в локальном агенте

**Files:**
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_local_agent_cli.py`

- [ ] **Step 1: Preserve and verify current outreach diagnostics**

Сохранить незакоммиченные `_write_outreach_send_failure` и `_outreach_failure_status`. Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py -q`. Expected: existing 410/422 tests pass before queue integration.

- [ ] **Step 2: Write failing producer isolation test**

При `agent_queue_enabled=True` `run_local_agent_once` должен создать заказ и job, но не вызывать `FakeAutopilotClient.analyze_order` внутри `on_match`. Передать `process_jobs=False` в тесте, чтобы доказать быстрое завершение producer-фазы.

- [ ] **Step 3: Implement enqueue and reconciliation**

После `handle_matched_post` вызывать `queue.enqueue(...)` вместо `_maybe_run_autopilot`. В начале цикла `release_expired_leases`, затем для каждого заказа `AWAITING_RESPONSE_APPROVAL` делать идемпотентный enqueue. При выключенной очереди оставить текущий синхронный путь.

- [ ] **Step 4: Make autopilot errors observable to worker**

Добавить в `_maybe_run_autopilot` keyword `raise_on_error: bool = False`. При true после безопасной записи/без Telegram-спама повторно выбрасывать исключение. Старые вызовы сохраняют прежнее поведение.

- [ ] **Step 5: Write failing worker lifecycle tests**

Проверить:

- успешный job вызывает AI один раз и становится `succeeded`;
- повторный запуск succeeded job не вызывает AI;
- timeout становится `pending` с будущим `available_at`;
- HTTP 422 становится `dead` и создает ровно одно Telegram-уведомление;
- исчерпавший `max_attempts` timeout становится `dead`;
- заказ с уже продвинутым статусом завершает job без внешнего действия.

- [ ] **Step 6: Implement bounded worker loop**

Добавить `_process_agent_jobs(...)`, обрабатывающий максимум `config.agent_jobs_per_cycle`. Каждая попытка пишет JSON-журнал; terminal failure пишет `dead.json`; после цикла обновляется `orders/reports/job_queue_health.json`.

- [ ] **Step 7: Run integration tests**

Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py tests/test_job_queue.py tests/test_job_worker.py -q`

Expected: all integration tests pass.

### Task 4: Документация, миграция и live-проверка

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`

- [ ] **Step 1: Document queue settings and runtime files**

Описать пять `AGENT_QUEUE_*`/`AGENT_JOB_*` переменных, `orders/agent_jobs.sqlite3`, `orders/<order_id>/jobs/` и `orders/reports/job_queue_health.json`. Указать, что SQLite не содержит клиентские файлы и не заменяет `state.json`.

- [ ] **Step 2: Run full verification**

Run: `PYTHONPATH=src pytest -q && python3 -m compileall -q src && git diff --check`

Expected: zero failures and exit code 0.

- [ ] **Step 3: Commit current outreach diagnostics and queue implementation**

Сначала зафиксировать существующие 410/422 diagnostics отдельным commit, затем очередь отдельным commit. Не удалять и не переписывать эти изменения.

- [ ] **Step 4: Reload LaunchAgent and verify migration**

Run: `launchctl kickstart -k gui/$(id -u)/com.codex.vacancy-agent`. Проверить `state = running`, пустой stderr, существование SQLite БД и `job_queue_health.json`. Убедиться, что текущие `awaiting_response_approval` заказы появились в очереди не более одного раза.

- [ ] **Step 5: Verify crash recovery**

На тестовой временной БД создать leased job с истекшим lease и запустить reconciler. Проверить возврат в `pending` и последующий успешный claim без отправки реального отклика.
