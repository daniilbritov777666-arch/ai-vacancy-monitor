# Telegram Freelance Agent

Локальный автономный агент для поиска и выполнения разовых IT-фриланс заказов в РФ-формате с помощью OpenAI-compatible API.

## Как работает

- GitHub Actions запускает проверку каждые 5 минут.
- Скрипт читает публичные страницы `https://t.me/s/<channel>`.
- Скрипт читает публичные RSS-ленты FL.ru/Freelancehunt и живые страницы разовых проектов Freelance.ru/Pchel.net.
- Kwork и Workzilla проверяются только на доступность: их публичные страницы не дают подтвержденный серверный поток живых проектов.
- В ручном режиме подходящие заказы отправляются в Telegram с кнопками подтверждения; в `autopilot` безопасные заказы проходят без кнопок.
- Локальный агент создает отдельную папку заказа в `orders/`.
- AI-слой может подготовить анализ, отклик, план, черновик результата и сообщение заказчику.
- В `autopilot` AI-задачи проходят через транзакционную SQLite-очередь: поиск не блокируется внешним API, временные ошибки повторяются, а просроченные lease восстанавливаются после перезапуска.
- Если заказ пришел с Freelancehunt и задан `FREELANCEHUNT_API_TOKEN`, автопилот отправляет первый безопасный отклик через официальный API Freelancehunt.
- Если в публичном проекте указан email и настроен SMTP, автопилот отправляет первый отклик по email. Если дополнительно настроен IMAP, агент читает входящие ответы, продолжает переписку, готовит выполнение и может сдавать результат по email.
- Если включен `AUTO_CONVERSATION_ENABLED`, локальный агент читает входящие треды Freelancehunt, сохраняет переписку в папку заказа, готовит AI-черновик ответа и уведомляет Telegram.
- Если включен `AUTO_REPLY_ENABLED`, безопасные последующие ответы отправляются заказчику на Freelancehunt автоматически.
- Если включен `AUTO_EXECUTION_ENABLED`, агент создает рабочий пакет выполнения и стартовые артефакты результата в папке заказа.
- Если включен `AUTO_EXECUTION_DRAFT_ENABLED`, агент собирает AI-пакет результата в `execution/generated/` и готовит сообщение сдачи в `outbox/delivery_message.md`.
- Если включен `AUTO_QUALITY_ENABLED`, первоначальный результат и автоправки проходят локальную и AI-проверку до отправки; после двух неудачных исправлений включается `quality_failed` без ручной карточки.
- Если включен `AUTO_DELIVERY_ENABLED`, прошедший проверку результат автоматически отправляется заказчику на Freelancehunt.
- Уже просмотренные посты сохраняются в `data/seen_posts.json`, чтобы не было дублей.
- Первый запуск только запоминает текущие посты и ничего не отправляет, чтобы не заспамить старыми вакансиями.

## Критерии отбора

Мониторинг пропускает только разовые задачи формата "сделал результат - получил оплату":

- Telegram-боты, chatbots, mini apps;
- автоматизации, интеграции, API, webhooks, n8n, Make, Zapier;
- парсеры, скрипты, простые Python/JS-задачи;
- тексты и контент, если это разовая понятная задача;
- Google Sheets/Excel автоматизации, формулы, макросы, дашборды.

Мониторинг отсекает вакансии и задачи вне текущего профиля:

- fulltime/part-time, 5/2, оклад, постоянная поддержка, долгосрочное сотрудничество;
- подбор товаров для маркетплейсов, ручную операционку и работу "по готовому алгоритму";
- сайты/лендинги без явной AI/IT-автоматизации в текущем профиле;
- таргет, реклама, маркетинг, Avito-продвижение;
- дизайн, баннеры, карточки, инфографика, презентации, монтаж;
- обход лимитов платформ, массовые аккаунты, накрутки, фишинг, вредоносное ПО и незаконный сбор персональных данных.

## GitHub Secrets

В репозитории открой `Settings -> Secrets and variables -> Actions -> New repository secret` и добавь:

- `TELEGRAM_BOT_TOKEN` - токен бота от `@BotFather`.
- `TELEGRAM_CHAT_ID` - `150761046`.

Токен не нужно хранить в коде.

## GitHub Variables

Необязательные переменные в `Settings -> Secrets and variables -> Actions -> Variables`:

- `TELEGRAM_CHANNELS` - список каналов через запятую. По умолчанию: `mari_vakansii,digitaltender,FreeVacanciesIT`.
- `RSS_FEEDS` - список RSS-лент через запятую. По умолчанию: `https://www.fl.ru/rss/projects.xml,https://freelancehunt.com/projects.rss`.
- `PUBLIC_PROJECT_SOURCES` - живые HTML-источники проектов. По умолчанию: `freelance_ru,pchel`.
- `PUBLIC_SOURCE_PROBES` - площадки только для проверки доступности. По умолчанию: `kwork,workzilla`.
- `SEND_FIRST_RUN` - поставь `true`, если хочешь отправить подходящие посты уже при первом запуске. По умолчанию старые посты только помечаются просмотренными.

## Локальная проверка

```bash
python3 -m pip install -r requirements-dev.txt
PYTHONPATH=src pytest -v
```

Ручной запуск без отправки невозможен без секретов:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" PYTHONPATH=src python3 -m vacancy_monitor.cli
```

## Локальный полуавтономный агент

Агент запускается на компьютере Даниила и создает папки заказов в `orders/`. Эта папка добавлена в `.gitignore`, потому что внутри будут переписка, ТЗ и клиентские материалы.

Форматы первой версии:

- язык сообщений и документов: русский;
- даты: `ДД.ММ.ГГГГ HH:MM МСК`;
- суммы: рубли;
- `AUTO_MODE=autopilot` включает автономный режим без Telegram-подтверждений для поддержанных Freelancehunt-действий;
- первый отклик, последующие ответы, подготовка результата, сдача результата, обработка правок и закрытие оплаченного заказа выполняются автоматически, если настроены токены и действие проходит safety-фильтр.

Запуск одной проверки:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

Постоянный локальный режим с проверкой раз в 5 минут и обработкой Telegram-кнопок:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" LOCAL_AGENT_LOOP=true PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

Для macOS LaunchAgent используй `scripts/run_local_agent.sh`. Если путь к проекту содержит кириллицу, запускай через ASCII-symlink, как описано в `docs/MARKETPLACES_PAYMENTS_RU.md`.

Дополнительные переменные:

- `ORDERS_PATH` - папка заказов. По умолчанию `orders`.
- `STATE_PATH` - файл просмотренных постов. По умолчанию `data/seen_posts.json`.
- `LOCAL_AGENT_INTERVAL_SECONDS` - интервал локального цикла. По умолчанию `300`.
- `AUTO_MODE` - режим AI-слоя:
  - `off` - только поиск и Telegram-кнопки, без OpenAI;
  - `draft` - AI готовит файлы в папке заказа, но статус не продвигает;
  - `autopilot` - AI готовит файлы, автоматически включает outreach/conversation/reply/execution/delivery/payment/revision-флаги и ведет безопасный заказ по цепочке без ручных подтверждений, если цена не выше лимита.
- `OPENAI_API_KEY` - ключ OpenAI API для режимов `draft` и `autopilot`.
- `OPENAI_MODEL` - модель OpenAI. По умолчанию `gpt-4.1-mini`.
- `OPENAI_BASE_URL` - базовый URL OpenAI-compatible API. По умолчанию `https://api.openai.com/v1`.
- `AUTO_MAX_PRICE_RUB` - максимальная цена, при которой `autopilot` может сам продвинуть заказ до черновика. По умолчанию `15000`.
- `AGENT_QUEUE_ENABLED` - включает устойчивую очередь AI-задач. По умолчанию включено при `AUTO_MODE=autopilot`.
- `AGENT_QUEUE_PATH` - путь к SQLite-файлу очереди. По умолчанию `orders/agent_jobs.sqlite3`.
- `AGENT_JOBS_PER_CYCLE` - максимум фоновых задач за один проход. По умолчанию `3`, диапазон `1..20`.
- `AGENT_JOB_MAX_ATTEMPTS` - максимум попыток задачи. По умолчанию `4`, диапазон `1..8`.
- `AGENT_JOB_LEASE_SECONDS` - время аренды задачи worker-процессом. По умолчанию `600`, диапазон `30..3600`.
- `AUTO_OUTREACH_ENABLED` - разрешает агенту самому отправлять первый безопасный отклик через API Freelancehunt или на опубликованный email после AI-проверки. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_OUTREACH_DAILY_LIMIT` - дневной лимит автооткликов. По умолчанию `3`.
- `AUTO_OUTREACH_MAX_AGE_HOURS` - максимальный возраст проекта для автоотклика. По умолчанию `24` часа.
- Перед ставкой на Freelancehunt агент проверяет профиль и текущий статус проекта через API. Отчёт сохраняется в `outbox/freelancehunt_preflight.json`; несовместимые типы сделки блокируются до отправки.
- `AUTO_CONVERSATION_ENABLED` - разрешает читать входящие треды Freelancehunt, сохранять их в `conversation.md`/`inbox/`, готовить AI-черновик ответа в `outbox/` и уведомлять Telegram. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REPLY_ENABLED` - разрешает агенту самому отправлять безопасные последующие ответы в тред Freelancehunt. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REPLY_DAILY_LIMIT` - дневной лимит автоответов в треды. По умолчанию `10`.
- `AUTO_EXECUTION_ENABLED` - создает рабочий пакет выполнения в `execution/` после ответа заказчика: контекст, чеклист, заметки и стартовые файлы результата. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_EXECUTION_DRAFT_ENABLED` - генерирует AI-пакет результата в `execution/generated/` и сообщение сдачи в `outbox/delivery_message.md`. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_DELIVERY_ENABLED` - разрешает агенту самому отправлять безопасный результат заказчику после генерации AI-пакета. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_DELIVERY_DAILY_LIMIT` - дневной лимит автосдачи результатов. По умолчанию `5`.
- `DELIVERY_PUBLIC_VERIFY_ENABLED` - перед отправкой на Freelancehunt проверяет публичный ZIP через HTTPS и сверяет его размер. По умолчанию включено вместе с `DELIVERY_TUNNEL_ENABLED`; отчёт сохраняется в `outbox/delivery_readiness.json`.
- `AUTO_QUALITY_ENABLED` - включает локальную и AI-проверку файлов перед первоначальной сдачей и отправкой правок. По умолчанию включено при `AUTO_MODE=autopilot`.
- `AUTO_QUALITY_MAX_REPAIRS` - максимальное число автоматических исправлений после замечаний. По умолчанию `2`, допустимый диапазон `0..5`.
- `EXECUTION_VERIFY_ENABLED` - запускает Python/JavaScript-пакеты в одноразовом контейнере перед AI-review и отправкой. В `autopilot` включено по умолчанию.
- `EXECUTION_TIMEOUT_SECONDS`, `EXECUTION_MEMORY_MB`, `EXECUTION_CPUS`, `EXECUTION_MAX_OUTPUT_BYTES` - лимиты изолированного запуска. По умолчанию `120`, `512`, `1.0`, `65536`.
- Установка runtime: `./scripts/setup_execution_runtime.sh`. Скрипт использует Homebrew/Colima или user-local Lima без admin-прав. Контейнер работает без сети, с read-only пакетом и без секретов агента.
- `AUTO_PAYMENT_WATCH_ENABLED` - проверяет собственные ставки через `/v2/my/bids`, распознает выбранного исполнителя и закрывает локальный заказ после финального статуса проекта. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_PAYMENT_REMINDER_ENABLED` - отправляет не более двух напоминаний по неоплаченному заказу: через 24 часа после запроса оплаты и через 48 часов после первого напоминания. После сигнала оплаты напоминания прекращаются.
- `AUTO_REVISION_ENABLED` - разрешает агенту самому обрабатывать безопасные правки после сдачи результата. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REVISION_DAILY_LIMIT` - дневной лимит автоматических правок. По умолчанию `5`.
- `AUTO_STATUS_REPORT_ENABLED` - отправляет Telegram-отчет состояния агента с live-аудитом API Freelancehunt. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_STATUS_REPORT_INTERVAL_MINUTES` - минимальный интервал между Telegram-отчетами. По умолчанию `360`.
- `FREELANCEHUNT_API_TOKEN` - API-токен Freelancehunt для отправки отклика через `POST /v2/projects/{project_id}/bids`.
- `FREELANCEHUNT_BID_SAFE_TYPE` - тип безопасной сделки Freelancehunt: `employer`, `developer`, `split` или `employer_cashless`. По умолчанию `employer`.
- `FREELANCEHUNT_BID_DAYS` - срок выполнения в днях для первого отклика. По умолчанию `2`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL` - SMTP для автоотклика на опубликованный email. Обычно порт `587` и STARTTLS; для SMTP SSL используется порт `465` и `SMTP_USE_SSL=true`.
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_USE_SSL` - входящая почта для ответов заказчиков после email-отклика. Обычно порт `993`, папка `INBOX`, `IMAP_USE_SSL=true`.
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `PAYMENT_RETURN_URL` - внешний платежный канал ЮKassa для email-заказов. Агент создает ссылку оплаты и добавляет ее в сообщение сдачи результата.
- `PAYMENT_INSTRUCTIONS_RU` - резервные РФ-реквизиты/инструкция оплаты для email-заказов, если ЮKassa не настроена. Без ЮKassa и без этой инструкции агент блокирует автосдачу email-заказа, чтобы не отправлять результат без платежного канала.

Файлы AI-слоя в папке заказа:

- `autopilot/analysis.json` - структурированный анализ заказа;
- `autopilot/outreach.md` - черновик первого отклика;
- `autopilot/execution_plan.md` - план выполнения;
- `deliverables/autopilot_result.md` - черновой результат;
- `outbox/customer_message.md` - сообщение заказчику для отправки.
- `payment/request.json` - созданный запрос оплаты для внешнего email-заказа.
- `outbox/freelancehunt_reply_<thread_id>.md` - AI-черновик ответа на входящее сообщение Freelancehunt.
- `outbox/freelancehunt_reply_<thread_id>.sent.json` - запись реально отправленного автоответа.
- `outbox/email_reply_<email>.md` - AI-черновик ответа на входящее письмо заказчика.
- `outbox/email_reply_<email>.sent.json` - запись реально отправленного email-ответа.
- `execution/` - рабочий пакет выполнения: контекст, чеклист, заметки и стартовые артефакты результата.
  - `execution/starter/bot.py` для Telegram-ботов.
  - `execution/starter/parser.py` для парсеров/автоматизаций.
  - `execution/drafts/spreadsheet_spec.md` для таблиц/дашбордов.
  - `execution/drafts/content_draft.md` для текстов/контента.
  - `execution/generated/` - AI-пакет результата, подготовленный к проверке.
- `outbox/delivery_message.md` - сообщение заказчику для сдачи результата.
- `outbox/delivery_approval_requested.json` - отметка, что карточка проверки результата уже отправлена в Telegram.
- `outbox/delivery_message.sent.json` - отметка, что результат отправлен заказчику автоматически или после кнопки `Разрешить отправку`.
- `quality/execution-verification-attempt-<номер>.json` и `quality/execution-verification-latest.json` - отчеты контейнерной проверки.
- `orders/reports/execution_runtime_health.json` - доступность Docker daemon и runtime-образов.
- `quality/attempt-<номер>.json` - отчет локальной и AI-проверки для одной попытки.
- `quality/latest.json` - последний вердикт качества.
- `quality/quality_failed.json` - окончательная блокировка после исчерпания автоматических исправлений.
- `payment/freelancehunt_bid.json` - последняя считанная собственная ставка, признак победителя и статус проекта Freelancehunt.
- `revisions/<revision_id>/` - пакет автоматической правки: запрос, файлы, сообщение сдачи и отметка отправки.
- `revisions/manual_review_required.json` - заблокированный запрос правок, который не был выполнен автоматически.
- `reports/freelancehunt_live_api_audit.json` - последний live-аудит `threads`/`my/bids` Freelancehunt.
- `reports/status_report.md` - последний Telegram-отчет состояния агента.
- `reports/public_sources_health.json` - результат последней проверки Freelance.ru, Pchel.net, Kwork и Workzilla.
- `reports/email_transport_health.json` - TCP-доступность SMTP/IMAP. Если логины настроены, но порты недоступны, email-каналы в плане автопилота блокируются до смены сети/фаервола.
- `reports/marketplace_autopilot_plan.json` и `reports/marketplace_autopilot_plan.md` - карта рабочих каналов: где агент может искать, отправлять отклик, вести переписку, отслеживать оплату и какие биржи заблокированы из-за отсутствия API/SMTP/РФ-платежей.
- `jobs/<job_id>.json` - безопасный журнал всех попыток фоновой задачи заказа.
- `jobs/dead.json` - окончательная ошибка фоновой задачи после исчерпания повторов.
- `orders/agent_jobs.sqlite3` - транзакционное планирование и lease; клиентские материалы и тексты заказов остаются в `state.json` и папках заказа.
- `reports/job_queue_health.json` - количества pending/leased/succeeded/dead и восстановленные lease.

Проверка готовности бирж, переписки и платежей:

```bash
PYTHONPATH=src python3 -m vacancy_monitor.business_setup
```

Подробная инструкция по регистрации и подключению: `docs/MARKETPLACES_PAYMENTS_RU.md`.

## Ограничения

GitHub Actions schedule не гарантирует запуск ровно в секунду и не умеет чаще одного раза в 5 минут. Приватные Telegram-каналы через `t.me/s` не читаются; бот увидит только публичные веб-доступные посты.

Полный цикл переписки, сдачи, статуса сделки и правок поддержан для Freelancehunt через официальный API. Freelance.ru и Pchel.net расширяют поиск; первый отклик отправляется только при явно опубликованном email и настроенном SMTP, а последующая автономная переписка по этим заказам требует IMAP-доступ к входящей почте. Биржевые действия без официального API, авторизованного канала или открытого контакта агент не имитирует.

На каждом локальном цикле агент также пишет `orders/reports/marketplace_autopilot_plan.md`. Этот отчет нужен для автономного режима: он показывает, какие площадки прямо сейчас пригодны для полного цикла, какие работают только как поиск, и что нужно подключить следующим слоем.
