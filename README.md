# Telegram Freelance Agent

Локальный полуавтономный агент для поиска разовых IT-фриланс заказов в РФ-формате и подготовки чернового выполнения с помощью Codex/ChatGPT/OpenAI.

## Как работает

- GitHub Actions запускает проверку каждые 5 минут.
- Скрипт читает публичные страницы `https://t.me/s/<channel>`.
- Скрипт также читает публичные RSS-ленты фриланс-заказов FL.ru и Freelancehunt.
- Подходящие заказы отправляются в Telegram с кнопками подтверждения.
- Локальный агент создает отдельную папку заказа в `orders/`.
- AI-слой может подготовить анализ, отклик, план, черновик результата и сообщение заказчику.
- Если заказ пришел с Freelancehunt и задан `FREELANCEHUNT_API_TOKEN`, кнопка `Одобрить отклик` отправляет первый отклик через официальный API Freelancehunt.
- Если включен `AUTO_CONVERSATION_ENABLED`, локальный агент читает входящие треды Freelancehunt, сохраняет переписку в папку заказа, готовит AI-черновик ответа и уведомляет Telegram.
- Если включен `AUTO_REPLY_ENABLED`, безопасные последующие ответы отправляются заказчику на Freelancehunt автоматически.
- Если включен `AUTO_EXECUTION_ENABLED`, агент создает рабочий пакет выполнения и стартовые артефакты результата в папке заказа.
- Если включен `AUTO_EXECUTION_DRAFT_ENABLED`, агент собирает AI-пакет результата в `execution/generated/` и готовит сообщение сдачи в `outbox/delivery_message.md`.
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
- первый отклик и последующие ответы могут отправляться автоматически только при включенных флагах и прохождении safety-фильтра;
- цена, сроки, отправка результата и оплата требуют подтверждения через Telegram.

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
  - `autopilot` - AI готовит файлы и переводит безопасный заказ до `draft_ready`, если цена не выше лимита.
- `OPENAI_API_KEY` - ключ OpenAI API для режимов `draft` и `autopilot`.
- `OPENAI_MODEL` - модель OpenAI. По умолчанию `gpt-4.1-mini`.
- `OPENAI_BASE_URL` - базовый URL OpenAI-compatible API. По умолчанию `https://api.openai.com/v1`.
- `AUTO_MAX_PRICE_RUB` - максимальная цена, при которой `autopilot` может сам продвинуть заказ до черновика. По умолчанию `15000`.
- `AUTO_OUTREACH_ENABLED` - разрешает агенту самому отправлять первый безопасный отклик на Freelancehunt после AI-проверки. По умолчанию выключено.
- `AUTO_OUTREACH_DAILY_LIMIT` - дневной лимит автооткликов. По умолчанию `3`.
- `AUTO_CONVERSATION_ENABLED` - разрешает читать входящие треды Freelancehunt, сохранять их в `conversation.md`/`inbox/`, готовить AI-черновик ответа в `outbox/` и уведомлять Telegram. По умолчанию выключено.
- `AUTO_REPLY_ENABLED` - разрешает агенту самому отправлять безопасные последующие ответы в тред Freelancehunt. По умолчанию выключено.
- `AUTO_REPLY_DAILY_LIMIT` - дневной лимит автоответов в треды. По умолчанию `10`.
- `AUTO_EXECUTION_ENABLED` - создает рабочий пакет выполнения в `execution/` после ответа заказчика: контекст, чеклист, заметки и стартовые файлы результата. По умолчанию выключено.
- `AUTO_EXECUTION_DRAFT_ENABLED` - генерирует AI-пакет результата в `execution/generated/` и сообщение сдачи в `outbox/delivery_message.md`. По умолчанию выключено.
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
- `outbox/delivery_message.md` - сообщение заказчику для сдачи результата после проверки.

Проверка готовности бирж, переписки и платежей:

```bash
PYTHONPATH=src python3 -m vacancy_monitor.business_setup
```

Подробная инструкция по регистрации и подключению: `docs/MARKETPLACES_PAYMENTS_RU.md`.

## Ограничения

GitHub Actions schedule не гарантирует запуск ровно в секунду и не умеет чаще одного раза в 5 минут. Приватные Telegram-каналы через `t.me/s` не читаются; бот увидит только публичные веб-доступные посты.

Сейчас автоотправка первого отклика, чтение входящей переписки, автоотправка безопасных последующих ответов, подготовка рабочих пакетов и AI-пакетов результата поддержаны для Freelancehunt через официальный API. Отправка результата и принятие оплаты остаются точками подтверждения.
