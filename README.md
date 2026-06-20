# Telegram Freelance Agent

Локальный автономный агент для поиска и выполнения разовых IT-фриланс заказов в РФ-формате с помощью OpenAI-compatible API.

## Как работает

- GitHub Actions запускает проверку каждые 5 минут.
- Скрипт читает публичные страницы `https://t.me/s/<channel>`.
- Скрипт также читает публичные RSS-ленты фриланс-заказов FL.ru и Freelancehunt.
- В ручном режиме подходящие заказы отправляются в Telegram с кнопками подтверждения; в `autopilot` безопасные заказы проходят без кнопок.
- Локальный агент создает отдельную папку заказа в `orders/`.
- AI-слой может подготовить анализ, отклик, план, черновик результата и сообщение заказчику.
- Если заказ пришел с Freelancehunt и задан `FREELANCEHUNT_API_TOKEN`, автопилот отправляет первый безопасный отклик через официальный API Freelancehunt.
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
- `AUTO_OUTREACH_ENABLED` - разрешает агенту самому отправлять первый безопасный отклик на Freelancehunt после AI-проверки. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_OUTREACH_DAILY_LIMIT` - дневной лимит автооткликов. По умолчанию `3`.
- `AUTO_OUTREACH_MAX_AGE_HOURS` - максимальный возраст проекта для автоотклика. По умолчанию `24` часа.
- `AUTO_CONVERSATION_ENABLED` - разрешает читать входящие треды Freelancehunt, сохранять их в `conversation.md`/`inbox/`, готовить AI-черновик ответа в `outbox/` и уведомлять Telegram. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REPLY_ENABLED` - разрешает агенту самому отправлять безопасные последующие ответы в тред Freelancehunt. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REPLY_DAILY_LIMIT` - дневной лимит автоответов в треды. По умолчанию `10`.
- `AUTO_EXECUTION_ENABLED` - создает рабочий пакет выполнения в `execution/` после ответа заказчика: контекст, чеклист, заметки и стартовые файлы результата. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_EXECUTION_DRAFT_ENABLED` - генерирует AI-пакет результата в `execution/generated/` и сообщение сдачи в `outbox/delivery_message.md`. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_DELIVERY_ENABLED` - разрешает агенту самому отправлять безопасный результат заказчику после генерации AI-пакета. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_DELIVERY_DAILY_LIMIT` - дневной лимит автосдачи результатов. По умолчанию `5`.
- `AUTO_QUALITY_ENABLED` - включает локальную и AI-проверку файлов перед первоначальной сдачей и отправкой правок. По умолчанию включено при `AUTO_MODE=autopilot`.
- `AUTO_QUALITY_MAX_REPAIRS` - максимальное число автоматических исправлений после замечаний. По умолчанию `2`, допустимый диапазон `0..5`.
- `AUTO_PAYMENT_WATCH_ENABLED` - проверяет собственные ставки через `/v2/my/bids`, распознает выбранного исполнителя и закрывает локальный заказ после финального статуса проекта. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REVISION_ENABLED` - разрешает агенту самому обрабатывать безопасные правки после сдачи результата. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_REVISION_DAILY_LIMIT` - дневной лимит автоматических правок. По умолчанию `5`.
- `AUTO_STATUS_REPORT_ENABLED` - отправляет Telegram-отчет состояния агента с live-аудитом API Freelancehunt. По умолчанию включено при `AUTO_MODE=autopilot`, иначе выключено.
- `AUTO_STATUS_REPORT_INTERVAL_MINUTES` - минимальный интервал между Telegram-отчетами. По умолчанию `360`.
- `FREELANCEHUNT_API_TOKEN` - API-токен Freelancehunt для отправки отклика через `POST /v2/projects/{project_id}/bids`.
- `FREELANCEHUNT_BID_SAFE_TYPE` - тип безопасной сделки Freelancehunt: `employer`, `developer`, `split` или `employer_cashless`. По умолчанию `employer`.
- `FREELANCEHUNT_BID_DAYS` - срок выполнения в днях для первого отклика. По умолчанию `2`.

Файлы AI-слоя в папке заказа:

- `autopilot/analysis.json` - структурированный анализ заказа;
- `autopilot/outreach.md` - черновик первого отклика;
- `autopilot/execution_plan.md` - план выполнения;
- `deliverables/autopilot_result.md` - черновой результат;
- `outbox/customer_message.md` - сообщение заказчику для отправки.
- `outbox/freelancehunt_reply_<thread_id>.md` - AI-черновик ответа на входящее сообщение Freelancehunt.
- `outbox/freelancehunt_reply_<thread_id>.sent.json` - запись реально отправленного автоответа.
- `execution/` - рабочий пакет выполнения: контекст, чеклист, заметки и стартовые артефакты результата.
  - `execution/starter/bot.py` для Telegram-ботов.
  - `execution/starter/parser.py` для парсеров/автоматизаций.
  - `execution/drafts/spreadsheet_spec.md` для таблиц/дашбордов.
  - `execution/drafts/content_draft.md` для текстов/контента.
  - `execution/generated/` - AI-пакет результата, подготовленный к проверке.
- `outbox/delivery_message.md` - сообщение заказчику для сдачи результата.
- `outbox/delivery_approval_requested.json` - отметка, что карточка проверки результата уже отправлена в Telegram.
- `outbox/delivery_message.sent.json` - отметка, что результат отправлен заказчику автоматически или после кнопки `Разрешить отправку`.
- `quality/attempt-<номер>.json` - отчет локальной и AI-проверки для одной попытки.
- `quality/latest.json` - последний вердикт качества.
- `quality/quality_failed.json` - окончательная блокировка после исчерпания автоматических исправлений.
- `payment/freelancehunt_bid.json` - последняя считанная собственная ставка, признак победителя и статус проекта Freelancehunt.
- `revisions/<revision_id>/` - пакет автоматической правки: запрос, файлы, сообщение сдачи и отметка отправки.
- `revisions/manual_review_required.json` - заблокированный запрос правок, который не был выполнен автоматически.
- `reports/freelancehunt_live_api_audit.json` - последний live-аудит `threads`/`my/bids` Freelancehunt.
- `reports/status_report.md` - последний Telegram-отчет состояния агента.

Проверка готовности бирж, переписки и платежей:

```bash
PYTHONPATH=src python3 -m vacancy_monitor.business_setup
```

Подробная инструкция по регистрации и подключению: `docs/MARKETPLACES_PAYMENTS_RU.md`.

## Ограничения

GitHub Actions schedule не гарантирует запуск ровно в секунду и не умеет чаще одного раза в 5 минут. Приватные Telegram-каналы через `t.me/s` не читаются; бот увидит только публичные веб-доступные посты.

Сейчас автоотправка первого отклика, чтение входящей переписки, автоотправка безопасных последующих ответов, подготовка рабочих пакетов, AI-пакетов результата, автосдача результата, watcher оплаты и автоправки поддержаны для Freelancehunt через официальный API. В `AUTO_MODE=autopilot` агент не ждет ручных подтверждений и действует сам в пределах настроенных лимитов, токенов и safety-фильтров.
