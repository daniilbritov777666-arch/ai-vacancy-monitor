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
    assert config.openai_base_url == "https://api.openai.com/v1"
    assert config.openai_api_key is None


def test_autopilot_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_MODE", "autopilot")
    monkeypatch.setenv("AUTO_MAX_PRICE_RUB", "9000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = Config.from_env()

    assert config.auto_mode == "autopilot"
    assert config.auto_max_price_rub == 9000
    assert config.openai_model == "gpt-test"
    assert config.openai_base_url == "https://api.example.com/v1"
    assert config.openai_api_key == "sk-test"


def test_freelancehunt_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("FREELANCEHUNT_API_TOKEN", "fh-token")
    monkeypatch.setenv("FREELANCEHUNT_BID_SAFE_TYPE", "split")
    monkeypatch.setenv("FREELANCEHUNT_BID_DAYS", "3")

    config = Config.from_env()

    assert config.freelancehunt_api_token == "fh-token"
    assert config.freelancehunt_bid_safe_type == "split"
    assert config.freelancehunt_bid_days == 3


def test_auto_outreach_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_OUTREACH_ENABLED", "true")
    monkeypatch.setenv("AUTO_OUTREACH_DAILY_LIMIT", "4")

    config = Config.from_env()

    assert config.auto_outreach_enabled is True
    assert config.auto_outreach_daily_limit == 4


def test_conversation_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_CONVERSATION_ENABLED", "true")

    config = Config.from_env()

    assert config.auto_conversation_enabled is True


def test_auto_reply_and_execution_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("AUTO_REPLY_DAILY_LIMIT", "7")
    monkeypatch.setenv("AUTO_EXECUTION_ENABLED", "true")

    config = Config.from_env()

    assert config.auto_reply_enabled is True
    assert config.auto_reply_daily_limit == 7
    assert config.auto_execution_enabled is True
