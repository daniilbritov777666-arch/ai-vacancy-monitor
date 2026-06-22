# Container Execution Verifier Design

## Цель

Добавить проверяемое фактическое выполнение сгенерированных программных проектов перед отправкой заказчику. Код из `execution/generated/` не должен выполняться непосредственно на macOS, получать секреты агента или обращаться в сеть.

## Runtime

На текущем Mac отсутствуют Docker, Podman и Colima. Локальным runtime становится Colima с Docker CLI, установленными через Homebrew. LaunchAgent использует тот же Docker context, что и интерактивный пользователь.

Если runtime не установлен или daemon недоступен, агент не отправляет программный результат и записывает `runtime_unavailable`. Тексты, Markdown и таблицы продолжают проходить существующую статическую quality-проверку без контейнера.

## Компоненты

### `ExecutionVerifier`

Новый модуль `vacancy_monitor.execution_verifier` получает путь `execution/generated/`, тип проекта и настройки лимитов. Он возвращает immutable `ExecutionVerificationReport`:

- `status`: `passed`, `failed`, `unsupported` или `runtime_unavailable`;
- `project_type`: `python`, `javascript` или `static`;
- `commands`: безопасные команды и их exit code;
- `started_at`, `finished_at`, `duration_seconds`;
- `stdout`, `stderr`, обрезанные до установленного лимита;
- `issues`: машинные коды и русские описания;
- `runtime`: версия Docker и использованный образ.

### Распознавание проекта

- Python: присутствует хотя бы один `.py`, `pyproject.toml`, `setup.py` или `requirements.txt`;
- JavaScript: присутствует `package.json` или файл `.js`, `.mjs`, `.cjs`;
- static: остальные файлы, включая Markdown, CSV, JSON и офисные документы.

Смешанный Python/JavaScript-пакет получает `unsupported`, чтобы агент не угадывал среду выполнения.

### Команды

Python-контейнер последовательно выполняет:

1. фиксированный AST syntax-check всех `.py` без импорта и записи `.pyc`;
2. `python -m pytest -q -p no:cacheprovider /workspace`, только если найден `test_*.py`, `*_test.py` или каталог `tests/`; `PYTHONDONTWRITEBYTECODE=1` запрещает запись bytecode.

JavaScript-контейнер выполняет `node --check` для каждого JS-файла. `npm install`, lifecycle scripts и произвольные команды из `package.json` автоматически не запускаются.

Static-пакеты не запускаются и получают `passed`, если существующий `check_generated_package` уже прошел.

## Контейнерная изоляция

Каждый программный пакет запускается отдельным `docker run --rm` с настройками:

- `--network none`;
- `--read-only`;
- `--cap-drop ALL`;
- `--security-opt no-new-privileges`;
- `--pids-limit 64`;
- `--cpus 1`;
- `--memory 512m`;
- `--memory-swap 512m`;
- `--user 65534:65534`;
- `--mount type=bind,src=<generated>,dst=/workspace,readonly`;
- отдельный `tmpfs` для `/tmp` объемом 64 MB;
- hard timeout процесса на стороне Python.

Переменные окружения, Keychain, домашняя папка, Docker socket и каталоги вне `generated/` не передаются. Символические ссылки в пакете запрещены до запуска. Абсолютные пути и выход из workspace не формируются.

## Образы

- Python: локальный `freelance-agent-python-runner:3.12-v1`, построенный setup-скриптом из `python:3.12-slim` с закрепленной версией pytest;
- JavaScript: `EXECUTION_NODE_IMAGE`, по умолчанию `node:22-slim`.

Образы предварительно загружаются при установке. Автоматический pull во время обработки заказа запрещен, чтобы worker не зависел от сети и не выполнял неожиданный образ.

## Интеграция с quality gate

Container verification выполняется после локальной проверки файлов и до AI-review. Для static-пакета дополнительный запуск не требуется.

При `failed` отчет добавляется к repair-инструкциям AI, после чего создается новый пакет и проверка повторяется в пределах `AUTO_QUALITY_MAX_REPAIRS`. При `unsupported` или `runtime_unavailable` программный результат сразу получает `quality_failed`: повторная генерация файлов не исправит отсутствующий runtime или неподдерживаемую среду. Обход контейнерной проверки не разрешен.

Успешный отчет сохраняется до отправки, а `_auto_send_delivery` требует `status=passed` для программных пакетов.

## Файлы и наблюдаемость

Для каждой попытки создаются:

- `execution/verification/attempt-<номер>.json`;
- `execution/verification/latest.json`;
- `execution/verification/stdout-<номер>.log`;
- `execution/verification/stderr-<номер>.log`.

Отчеты не содержат секретов. Вывод ограничивается `EXECUTION_MAX_OUTPUT_BYTES`, по умолчанию 64 KB на поток. Telegram получает только итоговый код ошибки после исчерпания автоматических исправлений.

## Конфигурация

- `EXECUTION_VERIFY_ENABLED`: по умолчанию включено при `AUTO_MODE=autopilot`;
- `EXECUTION_RUNTIME`: по умолчанию `docker`;
- `EXECUTION_PYTHON_IMAGE`: `freelance-agent-python-runner:3.12-v1`;
- `EXECUTION_NODE_IMAGE`: `node:22-slim`;
- `EXECUTION_TIMEOUT_SECONDS`: `120`, диапазон `10..600`;
- `EXECUTION_MEMORY_MB`: `512`, диапазон `128..2048`;
- `EXECUTION_CPUS`: `1.0`, диапазон `0.25..2.0`;
- `EXECUTION_MAX_OUTPUT_BYTES`: `65536`, диапазон `4096..262144`.

При `EXECUTION_VERIFY_ENABLED=false` сохраняется текущая статическая проверка. Этот режим предназначен для диагностики, но не является подтвержденным выполнением кода.

## Установка и обслуживание

Setup-скрипт проверяет Homebrew, устанавливает `colima` и `docker`, запускает Colima с ограниченными ресурсами и загружает два закрепленных образа. Скрипт идемпотентен и не хранит секреты.

Health-report `orders/reports/execution_runtime_health.json` содержит доступность Docker daemon, версии client/server, наличие образов и время проверки.

## Тестирование

Модульные тесты используют fake command runner и проверяют точный безопасный argv без запуска Docker. Интеграционные тесты после установки runtime выполняют валидный Python-пакет, синтаксически ошибочный пакет, timeout-процесс, попытку записи в read-only workspace и попытку сетевого доступа.

Полная проверка включает pytest, `compileall`, `git diff --check`, Docker smoke-test и перезапуск LaunchAgent. Реальные отклики и клиентские файлы при smoke-test не используются.

## Не входит в этот слой

- выполнение произвольных shell-команд, полученных от LLM;
- автоматическая установка зависимостей из проекта;
- доступ контейнера к интернету, API-ключам или Telegram;
- Windows/macOS GUI-проекты;
- деплой результата в production-инфраструктуру заказчика.
