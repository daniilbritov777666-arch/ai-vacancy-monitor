# Telegram Vacancy Monitor

Мониторинг публичных Telegram-вакансий для задач, которые можно взять без уверенного знания кода и закрывать с помощью Codex/ChatGPT/AI-инструментов.

## Как работает

- GitHub Actions запускает проверку каждые 5 минут.
- Скрипт читает публичные страницы `https://t.me/s/<channel>`.
- Скрипт также читает публичные RSS-ленты фриланс-заказов FL.ru и Freelancehunt.
- Подходящие посты отправляются в Telegram.
- Уже просмотренные посты сохраняются в `data/seen_posts.json`, чтобы не было дублей.
- Первый запуск только запоминает текущие посты и ничего не отправляет, чтобы не заспамить старыми вакансиями.

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

## Ограничения

GitHub Actions schedule не гарантирует запуск ровно в секунду и не умеет чаще одного раза в 5 минут. Приватные Telegram-каналы через `t.me/s` не читаются; бот увидит только публичные веб-доступные посты.
