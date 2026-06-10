from vacancy_monitor.config import Config


def test_default_sources_are_project_feeds_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.delenv("TELEGRAM_CHANNELS", raising=False)

    config = Config.from_env()

    assert config.channels == []
    assert "https://www.fl.ru/rss/projects.xml" in config.rss_feeds


def test_autopilot_config_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.delenv("AUTO_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = Config.from_env()

    assert config.auto_mode == "off"
    assert config.auto_max_price_rub == 15000
    assert config.openai_model
    assert config.openai_api_key is None


def test_autopilot_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_MODE", "autopilot")
    monkeypatch.setenv("AUTO_MAX_PRICE_RUB", "9000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = Config.from_env()

    assert config.auto_mode == "autopilot"
    assert config.auto_max_price_rub == 9000
    assert config.openai_model == "gpt-test"
    assert config.openai_api_key == "sk-test"
