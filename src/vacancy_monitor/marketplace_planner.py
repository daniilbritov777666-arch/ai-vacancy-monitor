from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from pathlib import Path

from vacancy_monitor.config import Config
from vacancy_monitor.email_transport_health import EmailTransportHealth
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
        _freelancehunt_channel(config=config),
        _fl_ru_channel(config=config),
        _public_email_channel(
            key="freelance_ru",
            name="Freelance.ru",
            configured="freelance_ru" in config.public_project_sources,
            health=health_by_source.get("freelance_ru"),
            email_health=email_health,
            config=config,
            priority=3,
        ),
        _public_email_channel(
            key="pchel",
            name="Pchel.net",
            configured="pchel" in config.public_project_sources,
            health=health_by_source.get("pchel"),
            email_health=email_health,
            config=config,
            priority=4,
        ),
        _probe_only_channel("kwork", "Kwork", health_by_source.get("kwork"), priority=5),
        _probe_only_channel("workzilla", "Workzilla", health_by_source.get("workzilla"), priority=6),
    ]
    ready_channels = [channel.key for channel in channels if _is_ready_channel(channel)]
    rf_payment_channels = _rf_payment_channels(config=config, env=values)
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


def _freelancehunt_channel(*, config: Config) -> MarketplaceChannel:
    blockers: list[str] = []
    if not config.freelancehunt_api_token:
        blockers.append("нет FREELANCEHUNT_API_TOKEN")
    if config.auto_mode != "autopilot":
        blockers.append("AUTO_MODE не autopilot")
    if not config.openai_api_key:
        blockers.append("нет OPENAI_API_KEY")
    if config.freelancehunt_api_token and not config.auto_outreach_enabled:
        blockers.append("официальный API создания ставок отключен площадкой")
    outreach = "auto" if config.freelancehunt_api_token and config.auto_outreach_enabled else "blocked"
    conversation = "auto" if config.freelancehunt_api_token and config.auto_conversation_enabled else "blocked"
    payment = (
        "platform_escrow_watch"
        if config.freelancehunt_api_token and config.auto_payment_watch_enabled
        else "platform_escrow_manual"
    )
    return MarketplaceChannel(
        key="freelancehunt",
        name="Freelancehunt",
        discovery=(
            "enabled"
            if (config.freelancehunt_api_source_enabled and config.freelancehunt_api_token)
            or any("freelancehunt.com" in feed for feed in config.rss_feeds)
            else "disabled"
        ),
        outreach=outreach,
        conversation=conversation,
        payment=payment,
        priority=1,
        blockers=blockers,
        notes_ru="API поддерживает поиск и существующие сделки; создание новой ставки отключено площадкой.",
    )


def _fl_ru_channel(*, config: Config) -> MarketplaceChannel:
    configured = any("fl.ru" in feed for feed in config.rss_feeds)
    return MarketplaceChannel(
        key="fl_ru",
        name="FL.ru",
        discovery="enabled" if configured else "disabled",
        outreach="draft_only",
        conversation="manual",
        payment="platform_manual",
        priority=2,
        blockers=["нет подтвержденного API автооткликов"],
        notes_ru="Используется как источник проектов через RSS без имитации браузера.",
    )


def _public_email_channel(
    *,
    key: str,
    name: str,
    configured: bool,
    health: PublicSourceHealth | None,
    email_health: EmailTransportHealth | None,
    config: Config,
    priority: int,
) -> MarketplaceChannel:
    blockers: list[str] = []
    if not configured:
        blockers.append("источник не включен")
    if health and health.status != "available":
        blockers.append(f"источник недоступен: {health.status}")
    if not (config.smtp_host and config.smtp_from):
        blockers.append("SMTP не настроен")
    if not config.imap_host:
        blockers.append("IMAP не настроен")
    smtp_ready = bool(config.smtp_host and config.smtp_from)
    imap_ready = bool(config.imap_host and config.smtp_host and config.smtp_from)
    if email_health is not None:
        if smtp_ready and not email_health.smtp_reachable:
            blockers.append(f"SMTP недоступен: {email_health.smtp_error or 'connection failed'}")
            smtp_ready = False
        if imap_ready and not email_health.imap_reachable:
            blockers.append(f"IMAP недоступен: {email_health.imap_error or 'connection failed'}")
            imap_ready = False
    outreach = "email_auto" if smtp_ready else "manual_or_email_only"
    conversation = "email_auto" if imap_ready else "email_if_customer_replies"
    return MarketplaceChannel(
        key=key,
        name=name,
        discovery="enabled" if configured and (health is None or health.status == "available") else "blocked",
        outreach=outreach,
        conversation=conversation,
        payment="external_or_manual",
        priority=priority,
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
    if config.freelancehunt_api_token:
        channels.append("Freelancehunt safe")
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
    if not any(channel.key == "freelancehunt" and _is_ready_channel(channel) for channel in channels):
        actions.append("Довести Freelancehunt до полного цикла: API-токен, autopilot, автоотклик, переписка, payment watcher.")
    if not any(channel.outreach == "email_auto" for channel in channels):
        actions.append("Подключить SMTP, чтобы автоотклик работал для публичных проектов с опубликованным email.")
    if not any(channel.conversation == "email_auto" for channel in channels):
        actions.append("Подключить IMAP, чтобы агент читал ответы заказчиков по email и продолжал цикл без ручного переноса.")
    if "ЮKassa" not in rf_payment_channels and not (env.get("YOOKASSA_SHOP_ID") and env.get("YOOKASSA_SECRET_KEY")):
        actions.append("Для внешних оплат добавить YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY; первые заказы вести через безопасные сделки бирж.")
    return actions


def _is_ready_channel(channel: MarketplaceChannel) -> bool:
    return (
        channel.discovery == "enabled"
        and channel.outreach == "auto"
        and channel.conversation == "auto"
        and channel.payment == "platform_escrow_watch"
        and not channel.blockers
    )


def _write_text_atomic(path: Path, text: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
