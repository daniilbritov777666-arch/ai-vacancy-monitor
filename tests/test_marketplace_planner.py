from dataclasses import replace
import json

from vacancy_monitor.config import Config
from vacancy_monitor.marketplace_planner import (
    build_marketplace_plan,
    format_marketplace_plan,
    write_marketplace_plan_report,
)
from vacancy_monitor.email_transport_health import EmailTransportHealth
from vacancy_monitor.public_sources import PublicSourceHealth


def make_config(tmp_path) -> Config:
    return Config(
        bot_token="token",
        chat_id="150761046",
        channels=[],
        rss_feeds=["https://freelancehunt.com/projects.rss", "https://www.fl.ru/rss/projects.xml"],
        state_path=tmp_path / "seen_posts.json",
        send_first_run=False,
        orders_path=tmp_path / "orders",
    )


def test_marketplace_plan_marks_freelancehunt_as_full_autopilot_channel(tmp_path):
    config = replace(
        make_config(tmp_path),
        auto_mode="autopilot",
        openai_api_key="sk-test",
        freelancehunt_api_token="fh-token",
        auto_outreach_enabled=True,
        auto_conversation_enabled=True,
        auto_payment_watch_enabled=True,
    )

    plan = build_marketplace_plan(config=config, public_health=[])

    freelancehunt = next(channel for channel in plan.channels if channel.key == "freelancehunt")
    assert freelancehunt.discovery == "enabled"
    assert freelancehunt.outreach == "auto"
    assert freelancehunt.conversation == "auto"
    assert freelancehunt.payment == "platform_escrow_watch"
    assert freelancehunt.priority == 1
    assert not freelancehunt.blockers
    assert plan.ready_channels == ["freelancehunt"]


def test_marketplace_plan_keeps_public_sources_discovery_only_without_email_sender(tmp_path):
    config = replace(
        make_config(tmp_path),
        public_project_sources=["freelance_ru", "pchel"],
        smtp_host=None,
        smtp_from=None,
    )
    health = [
        PublicSourceHealth(
            source="freelance_ru",
            url="https://freelance.ru/task",
            checked_at="2026-06-23T10:00:00+03:00",
            status="available",
            posts=4,
        ),
        PublicSourceHealth(
            source="pchel",
            url="https://pchel.net/jobs/",
            checked_at="2026-06-23T10:00:00+03:00",
            status="available",
            posts=2,
        ),
    ]

    plan = build_marketplace_plan(config=config, public_health=health)

    freelance_ru = next(channel for channel in plan.channels if channel.key == "freelance_ru")
    pchel = next(channel for channel in plan.channels if channel.key == "pchel")
    assert freelance_ru.discovery == "enabled"
    assert freelance_ru.outreach == "manual_or_email_only"
    assert "SMTP не настроен" in freelance_ru.blockers
    assert pchel.discovery == "enabled"
    assert pchel.posts_seen == 2
    assert plan.ready_channels == []


def test_marketplace_plan_marks_public_source_email_conversation_when_smtp_and_imap_are_ready(tmp_path):
    config = replace(
        make_config(tmp_path),
        public_project_sources=["freelance_ru"],
        smtp_host="smtp.example.ru",
        smtp_from="robot@example.ru",
        imap_host="imap.example.ru",
    )

    plan = build_marketplace_plan(config=config, public_health=[])

    freelance_ru = next(channel for channel in plan.channels if channel.key == "freelance_ru")
    assert freelance_ru.outreach == "email_auto"
    assert freelance_ru.conversation == "email_auto"
    assert "SMTP не настроен" not in freelance_ru.blockers
    assert "IMAP не настроен" not in freelance_ru.blockers


def test_marketplace_plan_blocks_email_auto_when_transport_is_unreachable(tmp_path):
    config = replace(
        make_config(tmp_path),
        public_project_sources=["freelance_ru"],
        smtp_host="smtp.yandex.ru",
        smtp_from="robot@example.ru",
        imap_host="imap.yandex.ru",
    )
    email_health = EmailTransportHealth(
        checked_at="2026-06-24T10:00:00+03:00",
        status="unavailable",
        smtp_configured=True,
        imap_configured=True,
        smtp_host="smtp.yandex.ru",
        smtp_port=465,
        imap_host="imap.yandex.ru",
        imap_port=993,
        smtp_reachable=False,
        imap_reachable=False,
        smtp_error="TimeoutError: timed out",
        imap_error="TimeoutError: timed out",
    )

    plan = build_marketplace_plan(config=config, public_health=[], email_health=email_health)

    freelance_ru = next(channel for channel in plan.channels if channel.key == "freelance_ru")
    assert freelance_ru.outreach == "manual_or_email_only"
    assert freelance_ru.conversation == "email_if_customer_replies"
    assert "SMTP недоступен: TimeoutError: timed out" in freelance_ru.blockers
    assert "IMAP недоступен: TimeoutError: timed out" in freelance_ru.blockers


def test_marketplace_plan_reports_rf_payment_readiness(tmp_path):
    config = replace(
        make_config(tmp_path),
        freelancehunt_api_token="fh-token",
        auto_payment_watch_enabled=True,
    )

    plan = build_marketplace_plan(
        config=config,
        public_health=[],
        env={"YOOKASSA_SHOP_ID": "shop", "YOOKASSA_SECRET_KEY": "secret"},
    )

    assert "Freelancehunt safe" in plan.rf_payment_channels
    assert "ЮKassa" in plan.rf_payment_channels
    assert "YOOKASSA_SHOP_ID" not in " ".join(plan.next_actions)


def test_write_marketplace_plan_report_outputs_json_and_markdown(tmp_path):
    config = replace(make_config(tmp_path), freelancehunt_api_token="fh-token")
    plan = build_marketplace_plan(config=config, public_health=[])

    json_path, markdown_path = write_marketplace_plan_report(config.orders_path / "reports", plan)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    text = markdown_path.read_text(encoding="utf-8")
    assert payload["checked_at"]
    assert payload["channels"][0]["key"] == "freelancehunt"
    assert "План автопилота по биржам" in text
    assert "Freelancehunt" in format_marketplace_plan(plan)
