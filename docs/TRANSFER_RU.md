# Перенос комплекта фриланс-агента

Дата упаковки: 04.06.2026.

## Что внутри

- `src/vacancy_monitor/` - код монитора, локального агента, фильтров, заказов, Telegram-кнопок и AI-автопилота.
- `tests/` - автотесты текущего поведения.
- `README.md` - описание проекта, режимов и переменных.
- `.env.example` - пример переменных окружения без секретов.
- `deploy/macos/com.codex.vacancy-agent.plist.example` - шаблон LaunchAgent для macOS.
- `docs/superpowers/specs/` и `docs/superpowers/plans/` - проектные спецификации и планы.

В архив не включаются секреты, `.git`, `orders/`, `data/seen_posts.json`, кэши Python и pytest.

## Текущая логика

Агент ищет только разовые заказы с оплатой за результат:

- Telegram-боты;
- автоматизации, интеграции, парсеры;
- тексты и контент как разовая задача;
- таблицы, Excel/Google Sheets и дашборды.

Агент отсекает:

- постоянные вакансии, оклад, 5/2, fulltime/part-time;
- маркетплейс-операционку и подбор товаров;
- обычные сайты/лендинги без текущего IT/AI-профиля;
- обход лимитов, массовые аккаунты, накрутки, фишинг, вредоносное ПО и незаконный сбор персональных данных.

## Режимы AI-слоя

- `AUTO_MODE=off` - только поиск заказов и кнопки в Telegram.
- `AUTO_MODE=draft` - AI готовит файлы в папке заказа, но статус заказа не продвигает.
- `AUTO_MODE=autopilot` - AI готовит файлы и переводит безопасный заказ в `draft_ready`, если цена не выше `AUTO_MAX_PRICE_RUB`.
- `AUTO_OUTREACH_ENABLED=false` - рабочее значение для текущего Freelancehunt: публичный API создания ставки отключён площадкой и возвращает `410 API v2 deprecation`. Поиск и подготовка отклика продолжаются; email можно включить после восстановления SMTP.
- `FREELANCEHUNT_API_SOURCE_ENABLED=true` и `FREELANCEHUNT_API_PAGES=1` - официальный API используется для поиска открытых проектов; дублирующий RSS Freelancehunt отключается автоматически.
- `FREELANCEHUNT_API_SKILL_IDS=180,169,22,86,178,189,150,197` - серверный фильтр целевых навыков для ботов, парсинга, Python, данных, автоматизаций, CRM и AI-текстов.
- `PUBLIC_PROJECT_SOURCES=freelance_ru,pchel,weblancer` - публичные страницы одноразовых проектов; вакансии, крипто, дизайн и долгосрочная работа отсекаются до создания заказа.
- API-источник пропускает проекты без поддерживаемой безопасной сделки и проекты с неподдерживаемой валютой. Сумма, валюта и тип сделки для ставки берутся из актуальных данных проекта.
- Для Freelancehunt перед `POST /bids` выполняется profile/project preflight. Capability профиля сохраняется в `orders/reports/freelancehunt_profile_capabilities.json`, данные конкретного проекта - в `outbox/freelancehunt_preflight.json`.
- `PUBLIC_PROJECT_SOURCES=freelance_ru,pchel` - включает дополнительные живые страницы разовых проектов.
- `PUBLIC_SOURCE_PROBES=kwork,workzilla` - проверяет доступность площадок без импорта демонстрационных заданий.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL` - канал первого email-отклика; если он не настроен, мониторинг источников все равно работает.
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_USE_SSL` - входящие email-ответы заказчиков; без IMAP email-канал работает только на первый отклик.
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `PAYMENT_RETURN_URL` - ЮKassa для внешних email-заказов.
- `PAYMENT_INSTRUCTIONS_RU` - резервная РФ-инструкция оплаты для email-заказов без ЮKassa.
- `AUTO_CONVERSATION_ENABLED=true` - агент читает входящие треды Freelancehunt и email-ответы заказчиков, сохраняет переписку, готовит AI-черновик ответа и уведомляет Telegram.
- `AUTO_REPLY_ENABLED=true` - агент сам отправляет безопасные последующие ответы в тред Freelancehunt или по email.
- `AUTO_EXECUTION_ENABLED=true` - агент создает рабочий пакет выполнения и стартовые артефакты результата после ответа заказчика.
- `AUTO_EXECUTION_DRAFT_ENABLED=true` - агент генерирует AI-пакет результата в `execution/generated/` и сообщение сдачи в `outbox/delivery_message.md`.
- `AUTO_DELIVERY_ENABLED=true` - агент сам отправляет безопасный результат заказчику после генерации AI-пакета и переводит заказ в `payment_requested`.
- `AUTO_DELIVERY_DAILY_LIMIT=5` - дневной лимит автосдачи результатов.
- `DELIVERY_PUBLIC_VERIFY_ENABLED=true` - не отправляет заказчику недоступную или повреждённую ссылку на ZIP; результат проверки сохраняется в `outbox/delivery_readiness.json`.
- `AUTO_QUALITY_ENABLED=true` - локальная и AI-проверка первоначального результата и автоправок до отправки.
- `AUTO_QUALITY_MAX_REPAIRS=2` - две автоматические попытки исправить замечания; затем `quality_failed` без ручного согласования.
- `EXECUTION_VERIFY_ENABLED=true` - обязательная изолированная проверка Python/JavaScript-файлов без сети и без записи в пакет.
- `AUTO_PAYMENT_WATCH_ENABLED=true` - агент проверяет `/v2/my/bids`, распознает победившую ставку и финальный статус проекта.
- `AUTO_PAYMENT_REMINDER_ENABLED=true` - агент напоминает об оплате через 24/72 часа, ведёт `payment/reminders.json` и прекращает напоминания после сигнала оплаты.
- `AUTO_REVISION_ENABLED=true` - агент сам обрабатывает безопасные правки после сдачи результата.
- `AUTO_REVISION_DAILY_LIMIT=5` - дневной лимит автоматических правок.
- `AUTO_STATUS_REPORT_ENABLED=true` - агент отправляет Telegram-отчет состояния с live-аудитом API Freelancehunt.
- `AUTO_STATUS_REPORT_INTERVAL_MINUTES=360` - минимальный интервал между отчетами.
- `AGENT_QUEUE_ENABLED=true` - AI-анализ заказов выполняется через устойчивую SQLite-очередь.
- `AGENT_QUEUE_PATH=orders/agent_jobs.sqlite3` - runtime-БД планирования; не содержит клиентские файлы и не заменяет `state.json`.
- `AGENT_JOBS_PER_CYCLE=3` - ограничение задач за проход.
- `AGENT_JOB_MAX_ATTEMPTS=4` - максимум попыток с задержками 1, 5 и 15 минут.
- `AGENT_JOB_LEASE_SECONDS=600` - lease автоматически восстанавливается после аварийного завершения процесса.
- В `autopilot` непрошедший quality gate не создает карточку согласования: отправка блокируется, а Telegram получает информационное уведомление.

AI-слой пишет:

- `orders/<order_id>/autopilot/analysis.json`;
- `orders/<order_id>/autopilot/outreach.md`;
- `orders/<order_id>/autopilot/execution_plan.md`;
- `orders/<order_id>/deliverables/autopilot_result.md`;
- `orders/<order_id>/outbox/customer_message.md`.
- `orders/<order_id>/outbox/freelancehunt_reply_<thread_id>.md`.
- `orders/<order_id>/outbox/freelancehunt_reply_<thread_id>.sent.json`.
- `orders/<order_id>/execution/`.
  - `execution/starter/bot.py` для Telegram-ботов.
  - `execution/starter/parser.py` для парсеров/автоматизаций.
  - `execution/drafts/spreadsheet_spec.md` для таблиц/дашбордов.
  - `execution/drafts/content_draft.md` для текстов/контента.
- `orders/<order_id>/execution/generated/`.
- `orders/<order_id>/outbox/delivery_message.md`.
- `orders/<order_id>/outbox/delivery_approval_requested.json`.
- `orders/<order_id>/outbox/delivery_message.sent.json`.
- `orders/<order_id>/quality/attempt-<номер>.json`.
- `orders/<order_id>/quality/latest.json`.
- `orders/<order_id>/quality/quality_failed.json`.
- `orders/<order_id>/quality/execution-verification-attempt-<номер>.json`.
- `orders/<order_id>/quality/execution-verification-latest.json`.
- `orders/<order_id>/payment/freelancehunt_bid.json`.
- `orders/<order_id>/revisions/<revision_id>/`.
- `orders/<order_id>/revisions/manual_review_required.json`.
- `orders/reports/freelancehunt_live_api_audit.json`.
- `orders/reports/status_report.md`.
- `orders/reports/public_sources_health.json`.
- `orders/reports/marketplace_autopilot_plan.json`.
- `orders/reports/marketplace_autopilot_plan.md`.
- `orders/reports/execution_runtime_health.json`.
- `orders/agent_jobs.sqlite3`.
- `orders/<order_id>/jobs/<job_id>.json` и `orders/<order_id>/jobs/dead.json`.

Важно: автоматическая отправка последующих сообщений включается отдельно через `AUTO_REPLY_ENABLED=true`, автосдача результата - через `AUTO_DELIVERY_ENABLED=true`, автоправки - через `AUTO_REVISION_ENABLED=true`, watcher статуса - через `AUTO_PAYMENT_WATCH_ENABLED=true`, Telegram-отчет - через `AUTO_STATUS_REPORT_ENABLED=true`. В `autopilot` рискованные и неопределенные заказы автоматически получают статус `skipped`, а заказ без рабочего канала связи - `contact_unavailable`, без запроса ручного подтверждения. Полный email-цикл требует SMTP для отправки и IMAP для входящих ответов; закрытие заказа на Freelancehunt выполняется только для победившей ставки при финальном статусе проекта из API. Фактическое поступление денег проверяется на балансе биржи.

После запуска смотри `orders/reports/marketplace_autopilot_plan.md`: там агент сам отмечает, какие биржи готовы к полному автопилоту, какие работают только как источники поиска, какие блокируются отсутствием API/SMTP, и какие РФ-платежные каналы доступны.

## Быстрый запуск на новом Mac

1. Распаковать архив в постоянную папку.
2. Установить зависимости:

```bash
python3 -m pip install -r requirements-dev.txt
```

3. Установить контейнерный runtime. Без admin-прав скрипт сам установит Lima и Docker CLI в `~/.local`:

```bash
./scripts/setup_execution_runtime.sh
```

4. Положить секреты в Keychain:

```bash
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w "TELEGRAM_TOKEN"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w "OPENAI_API_KEY"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.smtp-host -w "smtp.example.ru"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.smtp-username -w "robot@example.ru"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.smtp-password -w "SMTP_PASSWORD"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.smtp-from -w "robot@example.ru"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.imap-host -w "imap.example.ru"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.imap-username -w "robot@example.ru"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.imap-password -w "IMAP_PASSWORD"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.imap-folder -w "INBOX"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.yookassa-shop-id -w "YOOKASSA_SHOP_ID"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.yookassa-secret-key -w "YOOKASSA_SECRET_KEY"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.payment-return-url -w "https://example.ru/payment-return"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.payment-instructions-ru -w "РФ-реквизиты или инструкция оплаты"
```

5. Проверить вручную:

```bash
export TELEGRAM_BOT_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w)"
export OPENAI_API_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w)"
TELEGRAM_CHAT_ID=150761046 AUTO_MODE=autopilot PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

6. Для постоянного запуска скопировать `deploy/macos/com.codex.vacancy-agent.plist.example` в:

```bash
~/Library/LaunchAgents/com.codex.vacancy-agent.plist
```

7. В plist заменить `/ABSOLUTE/ASCII/PATH/TO/freelance-agent` на реальный путь к папке проекта или на ASCII-symlink. Если реальная папка содержит кириллицу, создай symlink:

```bash
ln -sfn "/путь/к/проекту/с/кириллицей" "$HOME/.codex/vibe-code-project"
```

И используй `$HOME/.codex/vibe-code-project` в plist.

8. Указать ASCII-папку логов, например:

```bash
mkdir -p "$HOME/.codex/vacancy-agent-logs"
```

9. Убедиться, что скрипт исполняемый:

```bash
chmod +x scripts/run_local_agent.sh
```

10. Запустить:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.codex.vacancy-agent.plist
launchctl print "gui/$(id -u)/com.codex.vacancy-agent"
```

## Проверка

```bash
PYTHONPATH=src pytest -v
```

На момент упаковки проверка проходила: `55 passed`.

## Что еще нужно для полной автономии

Для реального самостоятельного взятия заказов без ручной отправки нужен подключенный канал общения с заказчиком:

- API биржи, если биржа разрешает отклики и сообщения через API;
- Telegram-контакт заказчика, если заказчик сам дал контакт и разрешена отправка;
- отдельная интеграция с мессенджером или почтой, если есть официальный способ отправки.

Без такого канала агент безопасно готовит черновики и уведомления, но не пишет заказчику сам.
