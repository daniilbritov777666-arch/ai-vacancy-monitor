# Telegram Vacancy Monitor

Мониторинг публичных Telegram-вакансий для задач, которые можно взять без уверенного знания кода и закрывать с помощью Codex/ChatGPT/AI-инструментов.

## Как работает

- GitHub Actions запускает проверку каждые 5 минут.
- Скрипт читает публичные страницы `https://t.me/s/<channel>`.
- Скрипт также читает публичные RSS-ленты фриланс-заказов FL.ru и Freelancehunt.
- Подходящие посты отправляются в Telegram.
- Уже просмотренные посты сохраняются в `data/seen_posts.json`, чтобы не было дублей.
- Первый запуск только запоминает текущие посты и ничего не отправляет, чтобы не заспамить старыми вакансиями.

## Критерии отбора

Мониторинг пропускает только короткие технические заказы формата "сделал результат - получил оплату":

- сайты, лендинги, Tilda, WordPress, Webflow;
- Telegram-боты, chatbots, mini apps;
- автоматизации, интеграции, API, webhooks, n8n, Make, Zapier;
- CRM/no-code настройки: Bitrix24, amoCRM, воронки, роботы, триггеры;
- парсеры, скрипты, простые Python-задачи;
- Google Sheets/Excel автоматизации, формулы, макросы, дашборды.

Мониторинг отсекает контентные и долгосрочные задачи:

- копирайтинг, SMM, SEO, посты, сценарии, контент-планы;
- таргет, реклама, маркетинг, Avito-продвижение;
- дизайн, баннеры, карточки, инфографика, презентации, монтаж;
- fulltime/part-time, 5/2, оклад, постоянная поддержка, долгосрочное сотрудничество.

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
- первый отклик, цена, сроки, отправка результата и оплата требуют подтверждения через Telegram.

Запуск одной проверки:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

Постоянный локальный режим с проверкой раз в 5 минут и обработкой Telegram-кнопок:

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" LOCAL_AGENT_LOOP=true PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

Дополнительные переменные:

- `ORDERS_PATH` - папка заказов. По умолчанию `orders`.
- `STATE_PATH` - файл просмотренных постов. По умолчанию `data/seen_posts.json`.
- `LOCAL_AGENT_INTERVAL_SECONDS` - интервал локального цикла. По умолчанию `300`.

## Ограничения

GitHub Actions schedule не гарантирует запуск ровно в секунду и не умеет чаще одного раза в 5 минут. Приватные Telegram-каналы через `t.me/s` не читаются; бот увидит только публичные веб-доступные посты.
