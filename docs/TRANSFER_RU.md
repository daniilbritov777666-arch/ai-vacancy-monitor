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
- `AUTO_OUTREACH_ENABLED=true` - агент может сам отправлять первый безопасный отклик на Freelancehunt.
- `AUTO_CONVERSATION_ENABLED=true` - агент читает входящие треды Freelancehunt, сохраняет переписку, готовит AI-черновик ответа и уведомляет Telegram.
- `AUTO_REPLY_ENABLED=true` - агент сам отправляет безопасные последующие ответы в тред Freelancehunt.
- `AUTO_EXECUTION_ENABLED=true` - агент создает рабочий пакет выполнения после ответа заказчика.

AI-слой пишет:

- `orders/<order_id>/autopilot/analysis.json`;
- `orders/<order_id>/autopilot/outreach.md`;
- `orders/<order_id>/autopilot/execution_plan.md`;
- `orders/<order_id>/deliverables/autopilot_result.md`;
- `orders/<order_id>/outbox/customer_message.md`.
- `orders/<order_id>/outbox/freelancehunt_reply_<thread_id>.md`.
- `orders/<order_id>/outbox/freelancehunt_reply_<thread_id>.sent.json`.
- `orders/<order_id>/execution/`.

Важно: автоматическая отправка последующих сообщений включается отдельно через `AUTO_REPLY_ENABLED=true` и блокируется safety-фильтром при риск-флагах, паролях, обходах лимитов, накрутках и оплате вне безопасной сделки. Отправка результата и принятие оплаты остаются точками подтверждения.

## Быстрый запуск на новом Mac

1. Распаковать архив в постоянную папку.
2. Установить зависимости:

```bash
python3 -m pip install -r requirements-dev.txt
```

3. Положить секреты в Keychain:

```bash
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w "TELEGRAM_TOKEN"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w "OPENAI_API_KEY"
```

4. Проверить вручную:

```bash
export TELEGRAM_BOT_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w)"
export OPENAI_API_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w)"
TELEGRAM_CHAT_ID=150761046 AUTO_MODE=autopilot PYTHONPATH=src python3 -m vacancy_monitor.local_agent_cli
```

5. Для постоянного запуска скопировать `deploy/macos/com.codex.vacancy-agent.plist.example` в:

```bash
~/Library/LaunchAgents/com.codex.vacancy-agent.plist
```

6. В plist заменить `/ABSOLUTE/ASCII/PATH/TO/freelance-agent` на реальный путь к папке проекта или на ASCII-symlink. Если реальная папка содержит кириллицу, создай symlink:

```bash
ln -sfn "/путь/к/проекту/с/кириллицей" "$HOME/.codex/vibe-code-project"
```

И используй `$HOME/.codex/vibe-code-project` в plist.

7. Указать ASCII-папку логов, например:

```bash
mkdir -p "$HOME/.codex/vacancy-agent-logs"
```

8. Убедиться, что скрипт исполняемый:

```bash
chmod +x scripts/run_local_agent.sh
```

9. Запустить:

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
