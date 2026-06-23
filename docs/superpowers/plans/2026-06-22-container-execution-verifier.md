# Container Execution Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Безопасно выполнять и тестировать программные файлы из `execution/generated/` в одноразовых Docker-контейнерах перед AI-review и отправкой заказчику.

**Architecture:** `execution_verifier.py` определяет тип пакета и строит только фиксированные Docker argv без команд из клиентских файлов. Quality gate запускает verifier после статической проверки; failed-отчет участвует в AI repair, а unavailable/unsupported блокирует отправку. Colima/Docker устанавливаются отдельным идемпотентным setup-скриптом.

**Tech Stack:** Python 3.14, subprocess, Docker CLI, Colima, pytest, macOS LaunchAgent.

---

### Task 1: Модель verifier и безопасные Docker-команды

**Files:**
- Create: `src/vacancy_monitor/execution_verifier.py`
- Create: `tests/test_execution_verifier.py`

- [x] **Step 1: Write failing package detection tests**

Проверить `detect_project_type(path)` для Python, JavaScript, static и mixed. Mixed возвращает `unsupported`; symlink в любом месте дает issue `symlink_forbidden` до запуска команд.

- [x] **Step 2: Run RED tests**

Run: `PYTHONPATH=src pytest tests/test_execution_verifier.py -v`

Expected: import error for `vacancy_monitor.execution_verifier`.

- [x] **Step 3: Implement report types and detection**

Добавить `VerificationStatus(StrEnum)`, `CommandResult`, `VerificationIssue`, `ExecutionVerificationReport`, `ProjectType` и pure `detect_project_type`. Отчет имеет `to_dict()` без Path/Enum объектов.

- [x] **Step 4: Write failing Docker argv tests**

Fake runner сохраняет argv. Для Python проверить `docker image inspect` и `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --cpus 1.0 --memory 512m --memory-swap 512m --user 65534:65534`, readonly bind `/workspace` и tmpfs `/tmp`. Ни одна env текущего процесса не передается.

Проверить fixed AST-команду и pytest только при наличии тестов. JavaScript запускает `node --check` только для заранее найденных относительных JS-путей.

- [x] **Step 5: Implement `DockerExecutionVerifier`**

Конструктор принимает image names, timeout, resource limits, output limit и injectable runner. `verify(path)` сначала проверяет runtime/image, затем выполняет последовательность команд. Timeout превращается в issue `execution_timeout`; non-zero exit — `command_failed`; отсутствие daemon/image — `runtime_unavailable`.

- [x] **Step 6: Run GREEN tests**

Run: `PYTHONPATH=src pytest tests/test_execution_verifier.py -q`

Expected: all verifier unit tests pass.

### Task 2: Конфигурация и runtime health

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `tests/test_config.py`
- Create: `src/vacancy_monitor/execution_runtime.py`
- Create: `tests/test_execution_runtime.py`

- [x] **Step 1: Write failing config tests**

При `AUTO_MODE=autopilot` ожидать `execution_verify_enabled=True`, runtime `docker`, Python image `freelance-agent-python-runner:3.12-v1`, Node image `node:22-slim`, timeout 120, memory 512, cpus 1.0, max output 65536. Проверить bounds: timeout `10..600`, memory `128..2048`, cpus `0.25..2.0`, output `4096..262144`.

- [x] **Step 2: Implement config fields**

Добавить env-парсинг `EXECUTION_VERIFY_ENABLED`, `EXECUTION_RUNTIME`, `EXECUTION_PYTHON_IMAGE`, `EXECUTION_NODE_IMAGE`, `EXECUTION_TIMEOUT_SECONDS`, `EXECUTION_MEMORY_MB`, `EXECUTION_CPUS`, `EXECUTION_MAX_OUTPUT_BYTES`.

- [x] **Step 3: Write failing health report test**

Fake runner возвращает Docker client/server versions и image inspect statuses. `write_execution_runtime_health(path, ...)` атомарно сохраняет `available`, версии, наличие обоих образов и checked_at, не включая environment.

- [x] **Step 4: Implement runtime health**

Создать `execution_runtime.py` с bounded subprocess calls и атомарным JSON. Ошибка daemon или отсутствие образа дает `available=false` и безопасный тип ошибки.

- [x] **Step 5: Run task tests**

Run: `PYTHONPATH=src pytest tests/test_config.py tests/test_execution_runtime.py -q`

Expected: all config/runtime tests pass.

### Task 3: Интеграция в quality-repair gate

**Files:**
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_local_agent_cli.py`

- [x] **Step 1: Write failing quality integration tests**

Передать fake verifier в `_run_delivery_quality_gate`. Проверить:

- static package не требует Docker;
- passed verification допускает AI-review и delivery;
- failed verification добавляет русское описание к `repair_execution_package`, затем повторно проверяет исправленный пакет;
- runtime_unavailable и unsupported немедленно ставят `quality_failed` без AI repair;
- `quality/latest.json` содержит секцию `execution_verification`;
- программный пакет нельзя считать passed без успешного verifier report.

- [x] **Step 2: Implement verifier injection and report persistence**

Добавить optional `execution_verifier` в `_run_delivery_quality_gate`. При включенной config и программном пакете создать `DockerExecutionVerifier`; сохранять attempt/latest JSON и stdout/stderr logs в `execution/verification/`. Static использует synthetic passed report без subprocess.

- [x] **Step 3: Integrate repair instructions and terminal statuses**

`failed` issues добавляются к текущим local/AI instructions. `unsupported` и `runtime_unavailable` вызывают общий helper записи `quality_failed`, один Telegram notification и немедленный false.

- [x] **Step 4: Run integration tests**

Run: `PYTHONPATH=src pytest tests/test_local_agent_cli.py tests/test_execution_verifier.py -q`

Expected: all quality and verifier tests pass.

### Task 4: Идемпотентная установка Colima/Docker

**Files:**
- Create: `scripts/setup_execution_runtime.sh`
- Create: `docker/execution-python-runner/Dockerfile`
- Create: `docker/execution-python-runner/requirements.txt`
- Create: `tests/test_execution_runtime_setup.py`

- [x] **Step 1: Write static setup contract tests**

Проверить, что script использует `set -euo pipefail`, ставит `colima docker` через существующий Homebrew или user-local Lima/Docker CLI без admin-прав, запускает runtime с CPU/memory/disk limits, строит локальный Python runner и inspect-ит оба образа. Dockerfile использует Python 3.12 slim, непривилегированного пользователя и закрепленный pytest.

- [x] **Step 2: Implement setup assets**

Script не содержит секретов, повторный запуск безопасен, не выполняет `docker system prune`, не меняет LaunchAgent plist и не включает privileged containers.

- [x] **Step 3: Run setup contract tests**

Run: `PYTHONPATH=src pytest tests/test_execution_runtime_setup.py -q`

Expected: setup contract passes before system modification.

- [x] **Step 4: Install runtime**

Run: `bash scripts/setup_execution_runtime.sh`. Проверить `docker version`, `colima status`, `docker image inspect freelance-agent-python-runner:3.12-v1 node:22-slim`.

### Task 5: Live isolation tests, docs and LaunchAgent

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`

- [x] **Step 1: Run safe integration smoke tests**

Во временных папках под рабочим деревом, но не в `orders/`, проверить valid Python, syntax error, timeout, запись в `/workspace` и сетевой запрос. Ожидать passed только для valid; остальные получают соответствующие failed issues. Не использовать ключи или реальные клиентские файлы.

- [x] **Step 2: Document configuration and operation**

Добавить восемь `EXECUTION_*` переменных, setup command, verification files и правила unavailable/unsupported.

- [x] **Step 3: Run complete verification**

Run: `PYTHONPATH=src pytest -q && python3 -m compileall -q src && git diff --check`

Expected: zero failures.

- [x] **Step 4: Reload LaunchAgent**

Run: `launchctl kickstart -k gui/$(id -u)/com.codex.vacancy-agent`. Проверить state running, пустой stderr и `orders/reports/execution_runtime_health.json` с `available=true`.
