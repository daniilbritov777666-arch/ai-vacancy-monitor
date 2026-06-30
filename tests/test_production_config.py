import plistlib
from pathlib import Path


def test_launchagent_template_uses_rf_sources_only():
    path = Path("deploy/macos/com.codex.vacancy-agent.plist.example")
    payload = plistlib.loads(path.read_bytes())
    env = payload["EnvironmentVariables"]

    assert env["RSS_FEEDS"] == "https://www.fl.ru/rss/projects.xml"
    assert env["PUBLIC_PROJECT_SOURCES"] == "freelance_ru,pchel,weblancer"
    assert env["PUBLIC_SOURCE_PROBES"] == "kwork,workzilla"
    assert env["FREELANCEHUNT_API_SOURCE_ENABLED"] == "false"
    assert env["FREELANCEHUNT_BID_API_ENABLED"] == "false"


def test_migration_script_sets_rf_sources_without_deleting_secrets():
    text = Path("scripts/migrate_to_rf_marketplaces.sh").read_text(encoding="utf-8")

    assert "PlistBuddy" in text
    assert "freelance_ru,pchel,weblancer" in text
    assert "https://www.fl.ru/rss/projects.xml" in text
    assert "Delete" not in text
    assert "plutil -lint" in text
