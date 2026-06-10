# Биржи, переписка и платежи

Дата: 10.06.2026.

## Что можно автоматизировать

Автоматизация разрешена только через официальные API или явно разрешенный канал связи. Агент не должен обходить капчи, лимиты, антибот-защиту, пользовательские сессии браузера или правила биржи.

## Приоритет подключения

### 1. Freelancehunt

- Сайт API: `https://apidocs.freelancehunt.com/`
- Роль: основной кандидат для автооткликов и работы с заказами через API.
- Что нужно от Даниила:
  - зарегистрировать аккаунт фрилансера;
  - заполнить профиль, специализации и портфолио;
  - получить API-токен/доступ по документации;
  - положить токен в переменную `FREELANCEHUNT_API_TOKEN`.
- После этого можно добавить адаптер: поиск проектов, отклик, чтение сообщений, сохранение переписки в `orders/<id>/conversation.md`.

### 2. Upwork

- API: `https://www.upwork.com/developer/documentation/graphql/api/docs/index.html`
- Роль: международные заказы, но подключение дольше.
- Важно: API key проходит review. Нужны реальный профиль, адрес, фото и, вероятно, identity verification.
- Переменные после получения ключей:
  - `UPWORK_CLIENT_ID`;
  - `UPWORK_CLIENT_SECRET`;
  - `UPWORK_TENANT_ID`.

### 3. Freelancer.com

- API: `https://developers.freelancer.com/`
- Роль: международные проекты с developer API.
- Переменная после OAuth/API-настройки:
  - `FREELANCER_ACCESS_TOKEN`.

### 4. FL.ru

- Текущий режим: RSS discovery через `https://www.fl.ru/rss/projects.xml`.
- Автоотклики не подключать, пока не подтвержден официальный способ отправки откликов.
- Сейчас безопасный режим: агент находит проект, готовит отклик и кладет его в `outbox/`.

### 5. Kwork

- Старт для продавцов: `https://kwork.com/for-sellers`.
- Роль: витрина готовых услуг.
- Без подтвержденного официального API использовать только ручной режим: создать кворки, получать заказы через интерфейс, переносить ТЗ в агента.

## Канал переписки

Базовый разрешенный канал сейчас - Telegram-бот для управления агентом. Для переписки с заказчиком нужны один из вариантов:

1. API биржи с методами сообщений.
2. Telegram-контакт заказчика, который он сам дал в заказе или переписке.
3. Email или другой официальный канал, указанный заказчиком.

Пока канал не подключен, агент пишет файл:

```text
orders/<order_id>/outbox/customer_message.md
```

Этот текст можно отправить вручную или подключить к разрешенному adapter-у.

## Платежи

### Рекомендуемый первый этап: безопасная сделка внутри биржи

Для первых заказов лучше использовать внутреннюю безопасную сделку биржи. Это снижает риск неоплаты и не требует сразу строить отдельный checkout.

### ЮKassa

- API: `https://yookassa.ru/developers/api`
- Что нужно:
  - зарегистрировать кабинет ЮKassa;
  - пройти договор/идентификацию;
  - получить `shopId`;
  - создать секретный API-ключ;
  - настроить webhook для статусов платежей.
- Переменные:
  - `YOOKASSA_SHOP_ID`;
  - `YOOKASSA_SECRET_KEY`.

## Keychain на Mac

```bash
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w "OPENAI_API_KEY"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.freelancehunt-token -w "FREELANCEHUNT_API_TOKEN"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.yookassa-shop-id -w "YOOKASSA_SHOP_ID"
security add-generic-password -U -a vacancy-agent -s com.codex.vacancy-agent.yookassa-secret-key -w "YOOKASSA_SECRET_KEY"
```

## Проверка готовности

```bash
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="150761046" AUTO_MODE=autopilot OPENAI_API_KEY="..." PYTHONPATH=src python3 -m vacancy_monitor.business_setup
```

Если `OPENAI_API_KEY` не задан, автопилот не готов. Если не заданы токены бирж и ЮKassa, агент все равно может искать проекты и готовить черновики, но не сможет сам отправлять отклики через API и выставлять внешние платежи.
