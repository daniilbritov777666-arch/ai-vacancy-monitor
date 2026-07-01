from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from pathlib import Path

from vacancy_monitor.config import Config
from vacancy_monitor.email_transport_health import EmailTransportHealth
from vacancy_monitor.marketplace_channels import CHANNELS
from vacancy_monitor.order_models import format_moscow_time
from vacancy_monitor.public_sources import PublicSourceHealth


@dataclass(frozen=True)
class MarketplaceChannel:
    key: str
    name: str
    discovery: str
    outreach: str
    conversation: str
    payment: str
    priority: int
    posts_seen: int = 0
    blockers: list[str] | None = None
    notes_ru: str = ""


@dataclass(frozen=True)
class MarketplaceAutopilotPlan:
    checked_at: str
    ready_channels: list[str]
    rf_payment_channels: list[str]
    next_actions: list[str]
    channels: list[MarketplaceChannel]

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "ready_channels": self.ready_channels,
            "rf_payment_channels": self.rf_payment_channels,
            "next_actions": self.next_actions,
            "channels": [asdict(channel) for channel in self.channels],
        }


def build_marketplace_plan(
    *,
    config: Config,
    public_health: list[PublicSourceHealth],
    email_health: EmailTransportHealth | None = None,
    env: Mapping[str, str] | None = None,
) -> MarketplaceAutopilotPlan:
    values = env or os.environ
    health_by_source = {record.source: record for record in public_health}
    channels = [
        _fl_ru_channel(config=config),
        _public_email_channel(
            key="freelance_ru",
            configured="freelance_ru" in config.public_project_sources,
            health=health_by_source.get("freelance_ru"),
            email_health=email_health,
            config=config,
        ),
        _public_email_channel(
            key="pchel",
            configured="pchel" in config.public_project_sources,
            health=health_by_source.get("pchel"),
            email_health=email_health,
            config=config,
        ),
        _public_email_channel(
            key="weblancer",
            configured="weblancer" in config.public_project_sources,
            health=health_by_source.get("weblancer"),
            email_health=email_health,
            config=config,
        ),
        _probe_only_channel("kwork", "Kwork", health_by_source.get("kwork"), priority=5),
        _probe_only_channel("workzilla", "Workzilla", health_by_source.get("workzilla"), priority=6),
    ]
    rf_payment_channels = _rf_payment_channels(config=config, env=values)
    ready_channels = [
        channel.key
        for channel in channels
        if rf_payment_channels and _is_ready_channel(channel)
    ]
    next_actions = _next_actions(channels=channels, rf_payment_channels=rf_payment_channels, env=values)
    return MarketplaceAutopilotPlan(
        checked_at=format_moscow_time(),
        ready_channels=ready_channels,
        rf_payment_channels=rf_payment_channels,
        next_actions=next_actions,
        channels=channels,
    )


def write_marketplace_plan_report(reports_dir: Path, plan: MarketplaceAutopilotPlan) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "marketplace_autopilot_plan.json"
    markdown_path = reports_dir / "marketplace_autopilot_plan.md"
    _write_text_atomic(json_path, json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n")
    _write_text_atomic(markdown_path, format_marketplace_plan(plan))
    return json_path, markdown_path


def format_marketplace_plan(plan: MarketplaceAutopilotPlan) -> str:
    lines = [
        "План автопилота по биржам",
        "",
        f"Время: {plan.checked_at}",
        "",
        "Готовые каналы:",
    ]
    lines.extend(f"- {key}" for key in plan.ready_channels) if plan.ready_channels else lines.append("- нет")
    lines.extend(["", "РФ-платежи:"])
    lines.extend(f"- {name}" for name in plan.rf_payment_channels) if plan.rf_payment_channels else lines.append("- нет")
    lines.extend(["", "Каналы:"])
    for channel in sorted(plan.channels, key=lambda item: item.priority):
        blocker_text = "; ".join(channel.blockers or []) or "нет"
        lines.append(
            f"- {channel.name}: поиск={channel.discovery}, отклик={channel.outreach}, "
            f"переписка={channel.conversation}, оплата={channel.payment}, постов={channel.posts_seen}, "
            f"блокеры={blocker_text}"
        )
    lines.extend(["", "Следующие действия:"])
    lines.extend(f"- {action}" for action in plan.next_actions) if plan.next_actions else lines.append("- действий не требуется")
    return "\n".join(lines) + "\n"


def _fl_ru_channel(*, config: Config) -> MarketplaceChannel:
    capabilities = CHANNELS["fl_ru"]
    configured = any("fl.ru" in feed for feed in config.rss_feeds)
    browser_outreach = _browser_outreach_mode(config)
    blockers = []
    if browser_outreach == "browser_dry_run":
        blockers.append("нужен одноразовый вход в браузерный профиль")
    elif browser_outreach == "draft_only":
        blockers.append("браузерный адаптер отключен")
    return MarketplaceChannel(
        key=capabilities.key,
        name=capabilities.name,
        discovery="enabled" if configured else "disabled",
        outreach=browser_outreach,
        conversation=_browser_conversation_mode(config) or "manual",
        payment=capabilities.payment,
        priority=capabilities.priority,
        blockers=blockers,
        notes_ru="Поиск через RSS, отклик через изолированный браузерный профиль.",
    )


def _public_email_channel(
    *,
    key: str,
    configured: bool,
    health: PublicSourceHealth | None,
    email_health: EmailTransportHealth | None,
    config: Config,
) -> MarketplaceChannel:
    capabilities = CHANNELS[key]
    blockers: list[str] = []
    if not configured:
        blockers.append("источник не включен")
    if health and health.status != "available":
        blockers.append(f"источник недоступен: {health.status}")
    bridge_ready = bool(
        config.github_email_bridge_enabled
        and config.github_email_bridge_repo
        and config.github_email_bridge_token
        and config.smtp_from
    )
    if not ((config.smtp_host and config.smtp_from) or bridge_ready):
        blockers.append("SMTP не настроен")
    if not config.imap_host:
        blockers.append("IMAP не настроен")
    smtp_ready = bool(config.smtp_host and config.smtp_from) or bridge_ready
    imap_ready = bool(config.imap_host and config.smtp_host and config.smtp_from)
    if email_health is not None:
        if smtp_ready and not bridge_ready and not email_health.smtp_reachable:
            blockers.append(f"SMTP недоступен: {email_health.smtp_error or 'connection failed'}")
            smtp_ready = False
        if imap_ready and not email_health.imap_reachable:
            blockers.append(f"IMAP недоступен: {email_health.imap_error or 'connection failed'}")
            imap_ready = False
    browser_outreach = (
        _browser_outreach_mode(config)
        if config.marketplace_browser_enabled and key in {"freelance_ru", "weblancer"}
        else None
    )
    outreach = browser_outreach or ("email_auto" if smtp_ready else "manual_or_email_only")
    if browser_outreach == "browser_dry_run":
        blockers.append("нужен одноразовый вход в браузерный профиль")
    conversation = (
        _browser_conversation_mode(config)
        if config.marketplace_browser_enabled and key in {"freelance_ru", "weblancer"}
        else None
    ) or ("email_auto" if imap_ready else "email_if_customer_replies")
    return MarketplaceChannel(
        key=key,
        name=capabilities.name,
        discovery="enabled" if configured and (health is None or health.status == "available") else "blocked",
        outreach=outreach,
        conversation=conversation,
        payment=capabilities.payment,
        priority=capabilities.priority,
        posts_seen=health.posts if health else 0,
        blockers=blockers,
        notes_ru="Автоотклик возможен только если заказчик сам опубликовал email.",
    )


def _probe_only_channel(key: str, name: str, health: PublicSourceHealth | None, *, priority: int) -> MarketplaceChannel:
    status = health.status if health else "not_checked"
    return MarketplaceChannel(
        key=key,
        name=name,
        discovery="probe_only",
        outreach="manual",
        conversation="manual",
        payment="platform_manual",
        priority=priority,
        posts_seen=health.posts if health else 0,
        blockers=[f"нет серверного потока проектов: {status}"],
        notes_ru="Не используется для автооткликов без официального API или открытого контакта.",
    )


def _rf_payment_channels(*, config: Config, env: Mapping[str, str]) -> list[str]:
    channels = []
    if config.payment_instructions_ru:
        channels.append("СБП")
    if env.get("YOOKASSA_SHOP_ID") and env.get("YOOKASSA_SECRET_KEY"):
        channels.append("ЮKassa")
    return channels


def _next_actions(
    *,
    channels: list[MarketplaceChannel],
    rf_payment_channels: list[str],
    env: Mapping[str, str],
) -> list[str]:
    actions: list[str] = []
    if any(channel.outreach == "browser_dry_run" for channel in channels):
        actions.append("Войти в аккаунты бирж в браузерном профиле и проверить dry-run форм отклика.")
    if not any(channel.outreach == "email_auto" for channel in channels):
        actions.append("Подключить SMTP, чтобы автоотклик работал для публичных проектов с опубликованным email.")
    if not any(channel.conversation in {"email_auto", "platform_auto"} for channel in channels):
        actions.append("Подключить IMAP, чтобы агент читал ответы заказчиков по email и продолжал цикл без ручного переноса.")
    if not rf_payment_channels:
        actions.append("Добавить PAYMENT_INSTRUCTIONS_RU для оплаты по СБП или настроить ЮKassa.")
    return actions


def _browser_outreach_mode(config: Config) -> str:
    if not config.marketplace_browser_enabled:
        return "draft_only"
    return "browser_auto" if config.marketplace_browser_live_submit else "browser_dry_run"


def _browser_conversation_mode(config: Config) -> str | None:
    if not config.marketplace_browser_enabled or not config.marketplace_browser_conversation_enabled:
        return None
    if config.marketplace_browser_live_submit and config.marketplace_browser_reply_live:
        return "platform_auto"
    return "browser_conversation_dry_run"


def _is_ready_channel(channel: MarketplaceChannel) -> bool:
    return (
        channel.discovery == "enabled"
        and channel.outreach in {"email_auto", "browser_auto"}
        and channel.conversation in {"email_auto", "platform_auto"}
        and channel.payment not in {"none", "unavailable"}
        and not channel.blockers
    )


def _write_text_atomic(path: Path, text: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
