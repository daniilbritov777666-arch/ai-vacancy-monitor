from vacancy_monitor.marketplace_channels import CHANNELS, channel_for_source


def test_rf_channels_exclude_freelancehunt():
    assert "freelancehunt" not in CHANNELS
    assert {"fl_ru", "freelance_ru", "pchel", "weblancer"} <= set(CHANNELS)


def test_source_mapping_resolves_primary_rf_marketplaces():
    assert channel_for_source("freelance.ru").key == "freelance_ru"
    assert channel_for_source("www.fl.ru/rss/projects.xml").key == "fl_ru"
    assert channel_for_source("weblancer.net").browser_outreach is True


def test_unknown_source_has_no_marketplace_capabilities():
    assert channel_for_source("example.com") is None
