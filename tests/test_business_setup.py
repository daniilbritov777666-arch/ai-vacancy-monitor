from vacancy_monitor.business_setup import build_setup_report, marketplace_registry, payment_registry


def test_marketplace_registry_prioritizes_api_capable_sources():
    marketplaces = marketplace_registry()

    assert marketplaces[0].name == "Freelancehunt"
    assert marketplaces[0].automation_level == "api"
    assert "FREELANCEHUNT_API_TOKEN" in marketplaces[0].required_env
    assert any(item.name == "Kwork" and item.automation_level == "manual" for item in marketplaces)


def test_payment_registry_contains_yookassa_requirements():
    payments = payment_registry()
    yookassa = next(item for item in payments if item.name == "ЮKassa")

    assert yookassa.automation_level == "api"
    assert yookassa.required_env == ["YOOKASSA_SHOP_ID", "YOOKASSA_SECRET_KEY"]


def test_build_setup_report_marks_missing_blockers():
    report = build_setup_report(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "150761046",
            "OPENAI_API_KEY": "",
            "AUTO_MODE": "autopilot",
        }
    )

    assert report.ready_for_autopilot is False
    assert "OPENAI_API_KEY" in report.missing_required
    assert "FREELANCEHUNT_API_TOKEN" in report.missing_optional
    assert "YOOKASSA_SHOP_ID" in report.missing_optional


def test_build_setup_report_accepts_minimum_autopilot_env():
    report = build_setup_report(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "150761046",
            "OPENAI_API_KEY": "sk-test",
            "AUTO_MODE": "autopilot",
        }
    )

    assert report.ready_for_autopilot is True
    assert report.missing_required == []
