from vacancy_monitor.config import Config


def test_default_sources_are_project_feeds_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.delenv("TELEGRAM_CHANNELS", raising=False)

    config = Config.from_env()

    assert config.channels == []
    assert "https://www.fl.ru/rss/projects.xml" in config.rss_feeds
