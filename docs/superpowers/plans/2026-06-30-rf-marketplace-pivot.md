# RF Marketplace Pivot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести production-агента с Freelancehunt на РФ-доступные источники разовых IT-заказов и правдиво маршрутизировать только реально доступные email/платформенные каналы.

**Architecture:** Новый реестр возможностей площадок отделяет поиск от отклика, переписки и оплаты. Конфигурация отключает Freelancehunt по умолчанию, планировщик строит отчёт из реестра, а локальный агент отправляет только email с опубликованным адресом и сохраняет платформенные проекты как требующие доступного браузерного канала.

**Tech Stack:** Python 3.14, dataclasses, pytest, BeautifulSoup, JSON state, GitHub Actions email bridge, macOS LaunchAgent.

---

## File map

- Create `src/vacancy_monitor/marketplace_channels.py`: декларативный реестр площадок и их возможностей.
- Create `tests/test_marketplace_channels.py`: контракт реестра и РФ-политики.
- Modify `src/vacancy_monitor/config.py`: РФ-доступные defaults и явный флаг legacy Freelancehunt.
- Modify `tests/test_config.py`: defaults без Freelancehunt.
- Modify `src/vacancy_monitor/marketplace_planner.py`: отчёт из реестра, Weblancer и СБП, без рекомендаций Freelancehunt.
- Modify `tests/test_marketplace_planner.py`: новые приоритеты, blockers и ready semantics.
- Modify `src/vacancy_monitor/order_models.py`: платформенный контакт для проектов без email.
- Modify `tests/test_order_models.py`: email-first и platform-browser fallback.
- Modify `src/vacancy_monitor/local_agent_cli.py`: терминальные статусы и отсутствие ложных сообщений об отправке.
- Modify `tests/test_local_agent_cli.py` or existing focused local-agent tests: маршрутизация platform-browser/email.
- Modify `deploy/macos/com.codex.vacancy-agent.plist.example`, `scripts/run_local_agent.sh`, `README.md`, `docs/TRANSFER_RU.md`: production-конфигурация и инструкция запуска.

### Task 1: Marketplace capability registry

**Files:**
- Create: `src/vacancy_monitor/marketplace_channels.py`
- Create: `tests/test_marketplace_channels.py`

- [ ] **Step 1: Write failing registry tests**

```python
from vacancy_monitor.marketplace_channels import CHANNELS, channel_for_source


def test_rf_channels_exclude_freelancehunt():
    assert "freelancehunt" not in CHANNELS
    assert {"fl_ru", "freelance_ru", "pchel", "weblancer"} <= set(CHANNELS)


def test_source_mapping_prefers_email_then_platform_browser():
    assert channel_for_source("freelance.ru").key == "freelance_ru"
    assert channel_for_source("www.fl.ru/rss/projects.xml").key == "fl_ru"
    assert channel_for_source("weblancer.net").browser_outreach is True
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_channels.py`

Expected: FAIL with `ModuleNotFoundError: vacancy_monitor.marketplace_channels`.

- [ ] **Step 3: Implement immutable registry**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketplaceCapabilities:
    key: str
    name: str
    source_markers: tuple[str, ...]
    email_outreach: bool
    browser_outreach: bool
    platform_conversation: bool
    payment: str
    priority: int


CHANNELS = {
    "fl_ru": MarketplaceCapabilities("fl_ru", "FL.ru", ("fl.ru",), False, True, True, "platform_or_direct", 1),
    "freelance_ru": MarketplaceCapabilities("freelance_ru", "Freelance.ru", ("freelance.ru", "freelance_ru"), True, True, True, "platform_or_direct", 2),
    "pchel": MarketplaceCapabilities("pchel", "Pchel.net", ("pchel.net", "pchel"), True, True, False, "direct", 3),
    "weblancer": MarketplaceCapabilities("weblancer", "Weblancer", ("weblancer.net", "weblancer"), True, True, True, "platform_or_direct", 4),
}


def channel_for_source(source: str) -> MarketplaceCapabilities | None:
    lowered = source.lower()
    return next((item for item in CHANNELS.values() if any(marker in lowered for marker in item.source_markers)), None)
```

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_channels.py`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/marketplace_channels.py tests/test_marketplace_channels.py
git commit -m "feat: add RF marketplace capability registry"
```

### Task 2: Disable Freelancehunt discovery by default

**Files:**
- Modify: `src/vacancy_monitor/config.py`
- Modify: `tests/test_config.py`
- Modify: `src/vacancy_monitor/cli.py`

- [ ] **Step 1: Add failing defaults test**

```python
def test_rf_defaults_do_not_enable_freelancehunt(monkeypatch):
    for name in ("RSS_FEEDS", "FREELANCEHUNT_API_SOURCE_ENABLED", "FREELANCEHUNT_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    config = Config.from_env()

    assert all("freelancehunt" not in feed for feed in config.rss_feeds)
    assert config.freelancehunt_api_source_enabled is False
    assert config.public_project_sources == ["freelance_ru", "pchel", "weblancer"]
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_config.py::test_rf_defaults_do_not_enable_freelancehunt`

Expected: FAIL because autopilot currently enables the API source.

- [ ] **Step 3: Change defaults and remove implicit enablement**

```python
DEFAULT_RSS_FEEDS = ["https://www.fl.ru/rss/projects.xml"]

freelancehunt_api_source_enabled = _env_bool(
    "FREELANCEHUNT_API_SOURCE_ENABLED",
    default=False,
)
```

Ensure `cli.py` fetches Freelancehunt only when the explicit flag is true and a token exists; public sources and FL.ru RSS remain unchanged.

- [ ] **Step 4: Verify config and CLI tests**

Run: `PYTHONPATH=src pytest -q tests/test_config.py tests/test_cli.py`

Expected: all tests pass after updating legacy expectations to explicit opt-in.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/config.py src/vacancy_monitor/cli.py tests/test_config.py tests/test_cli.py
git commit -m "feat: default discovery to RF marketplaces"
```

### Task 3: Rebuild marketplace planning and reports

**Files:**
- Modify: `src/vacancy_monitor/marketplace_planner.py`
- Modify: `tests/test_marketplace_planner.py`

- [ ] **Step 1: Replace Freelancehunt-first expectations with RF channels**

```python
def test_marketplace_plan_prioritizes_rf_channels_and_omits_freelancehunt(tmp_path):
    config = replace(
        make_config(tmp_path),
        public_project_sources=["freelance_ru", "pchel", "weblancer"],
        payment_instructions_ru="Оплата по СБП",
    )
    plan = build_marketplace_plan(config=config, public_health=[])

    assert [channel.key for channel in plan.channels[:4]] == ["fl_ru", "freelance_ru", "pchel", "weblancer"]
    assert all(channel.key != "freelancehunt" for channel in plan.channels)
    assert "СБП" in plan.rf_payment_channels
    assert "Freelancehunt" not in " ".join(plan.next_actions)
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_planner.py`

Expected: FAIL because current report begins with Freelancehunt and omits Weblancer.

- [ ] **Step 3: Generate channels from `CHANNELS`**

Refactor `build_marketplace_plan()` to create FL.ru separately from RSS health and create public channels using the registry. Add Weblancer health. Remove `_freelancehunt_channel()` from the active list, remove the Freelancehunt next action, and report `СБП` when `config.payment_instructions_ru` is non-empty.

Update readiness so a channel is ready when discovery is enabled, at least one outbound transport is `email_auto` or `browser_auto`, conversation is not `blocked`, a payment route exists, and blockers contain no terminal transport error.

- [ ] **Step 4: Verify planner tests**

Run: `PYTHONPATH=src pytest -q tests/test_marketplace_planner.py`

Expected: all tests pass; rendered report contains FL.ru, Freelance.ru, Pchel.net and Weblancer, and contains no active Freelancehunt recommendation.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/marketplace_planner.py tests/test_marketplace_planner.py
git commit -m "feat: plan autopilot around RF marketplaces"
```

### Task 4: Truthful outreach routing

**Files:**
- Modify: `src/vacancy_monitor/order_models.py`
- Modify: `src/vacancy_monitor/local_agent_cli.py`
- Modify: `tests/test_order_models.py`
- Modify: `tests/test_local_agent_cli.py`

- [ ] **Step 1: Write failing order contact tests**

```python
def test_public_email_is_preferred_over_platform_browser():
    post = Post(source="freelance.ru", post_id="freelance_ru:10", url="https://freelance.ru/task/view/10", text="Пишите client@example.ru")
    order = make_order_from_post(post, category="Автоматизации и парсеры")
    assert order.contact == CustomerContact(channel="email", value="client@example.ru", can_auto_send=True)


def test_platform_project_without_email_keeps_browser_route():
    post = Post(source="weblancer.net", post_id="weblancer:20", url="https://www.weblancer.net/freelance/test-20/", text="Разовый проект")
    order = make_order_from_post(post, category="Telegram-боты")
    assert order.contact == CustomerContact(channel="platform_browser", value="weblancer", can_auto_send=False)
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_order_models.py`

Expected: second test fails with `contact is None`.

- [ ] **Step 3: Add registry fallback and terminal browser blocker**

After email extraction, resolve `channel_for_source(post.source)` and return:

```python
if channel and channel.browser_outreach:
    return CustomerContact(channel="platform_browser", value=channel.key, can_auto_send=False)
```

In `_maybe_auto_send_outreach()`, write `outbox/outreach_channel_blocked.json` and set `CONTACT_UNAVAILABLE` when `platform_browser` has no configured adapter. Do not emit “отправлен” and do not retry each loop. Keep email behavior unchanged.

- [ ] **Step 4: Verify focused outreach tests**

Run: `PYTHONPATH=src pytest -q tests/test_order_models.py tests/test_local_agent_cli.py -k 'outreach or contact or platform'`

Expected: email sends once; platform-browser order is recorded once as blocked; no duplicate notifications.

- [ ] **Step 5: Commit**

```bash
git add src/vacancy_monitor/order_models.py src/vacancy_monitor/local_agent_cli.py tests/test_order_models.py tests/test_local_agent_cli.py
git commit -m "fix: route outreach only through available channels"
```

### Task 5: Production configuration and operator documentation

**Files:**
- Modify: `deploy/macos/com.codex.vacancy-agent.plist.example`
- Modify: `scripts/run_local_agent.sh`
- Modify: `README.md`
- Modify: `docs/TRANSFER_RU.md`
- Create: `scripts/migrate_to_rf_marketplaces.sh`
- Test: `tests/test_production_config.py`

- [ ] **Step 1: Write failing production-config test**

```python
def test_launchagent_template_uses_rf_sources_only():
    text = Path("deploy/macos/com.codex.vacancy-agent.plist.example").read_text()
    assert "https://www.fl.ru/rss/projects.xml" in text
    assert "freelance_ru,pchel,weblancer" in text
    assert "https://freelancehunt.com/projects.rss" not in text
    assert "<false/>" in text or "FREELANCEHUNT_API_SOURCE_ENABLED" not in text
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src pytest -q tests/test_production_config.py`

Expected: FAIL because the template still contains legacy settings or lacks explicit RF sources.

- [ ] **Step 3: Add idempotent migration script**

`scripts/migrate_to_rf_marketplaces.sh` must use `/usr/libexec/PlistBuddy` to set:

```text
RSS_FEEDS=https://www.fl.ru/rss/projects.xml
PUBLIC_PROJECT_SOURCES=freelance_ru,pchel,weblancer
PUBLIC_SOURCE_PROBES=kwork,workzilla
FREELANCEHUNT_API_SOURCE_ENABLED=false
FREELANCEHUNT_BID_API_ENABLED=false
```

The script must not remove Keychain secrets or historical order folders. It validates the plist with `plutil -lint` and prints the exact `launchctl kickstart` command.

- [ ] **Step 4: Update docs and verify**

Run:

```bash
zsh -n scripts/migrate_to_rf_marketplaces.sh scripts/run_local_agent.sh
plutil -lint deploy/macos/com.codex.vacancy-agent.plist.example
PYTHONPATH=src pytest -q tests/test_production_config.py
```

Expected: shell syntax valid, plist valid, production test passes.

- [ ] **Step 5: Commit**

```bash
git add deploy/macos/com.codex.vacancy-agent.plist.example scripts/run_local_agent.sh scripts/migrate_to_rf_marketplaces.sh README.md docs/TRANSFER_RU.md tests/test_production_config.py
git commit -m "ops: migrate agent to RF marketplace sources"
```

### Task 6: Full verification and live rollout

**Files:**
- Modify only if verification exposes a defect in files from Tasks 1-5.

- [ ] **Step 1: Run static and full test verification**

```bash
git diff --check
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src pytest -q
```

Expected: no diff errors, compile succeeds, all tests pass.

- [ ] **Step 2: Run migration and restart service**

```bash
scripts/migrate_to_rf_marketplaces.sh "$HOME/Library/LaunchAgents/com.codex.vacancy-agent.plist"
launchctl kickstart -k "gui/$(id -u)/com.codex.vacancy-agent"
```

Expected: migration prints validated plist; LaunchAgent receives a new PID.

- [ ] **Step 3: Verify live state and reports**

```bash
launchctl print "gui/$(id -u)/com.codex.vacancy-agent" | grep -E 'state =|pid =|last exit code'
sleep 130
sed -n '1,220p' orders/reports/marketplace_autopilot_plan.md
sed -n '1,220p' orders/reports/public_sources_health.json
```

Expected: `state = running`; report contains four primary RF channels, no Freelancehunt next action, and fresh source timestamps.

- [ ] **Step 4: Verify no false external actions**

Inspect orders created after restart. Every `outreach_sent` order must contain a `.sent.json` transport record. Platform projects without an adapter must be `contact_unavailable` with `outbox/outreach_channel_blocked.json`, never `outreach_sent`.

- [ ] **Step 5: Commit any verification fix and push**

```bash
git status --short
git push origin codex/public-project-sources
```

Expected: clean worktree after any necessary focused fix; branch pushed successfully.
