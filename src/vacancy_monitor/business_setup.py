from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Mapping


@dataclass(frozen=True)
class IntegrationOption:
    name: str
    url: str
    automation_level: str
    required_env: list[str]
    notes_ru: str


@dataclass(frozen=True)
class SetupReport:
    ready_for_autopilot: bool
    missing_required: list[str]
    missing_optional: list[str]
    marketplaces: list[IntegrationOption]
    payments: list[IntegrationOption]


def marketplace_registry() -> list[IntegrationOption]:
    return [
        IntegrationOption(
            name="Freelancehunt",
            url="https://apidocs.freelancehunt.com/",
            automation_level="api",
            required_env=["FREELANCEHUNT_API_TOKEN"],
            notes_ru="Есть API 2.0 с авторизацией; кандидат N1 для легальной автоматизации откликов.",
        ),
        IntegrationOption(
            name="Upwork",
            url="https://www.upwork.com/developer/documentation/graphql/api/docs/index.html",
            automation_level="api_review",
            required_env=["UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET", "UPWORK_TENANT_ID"],
            notes_ru="API есть, но ключ проходит ревью; нужен заполненный профиль и проверка личности.",
        ),
        IntegrationOption(
            name="Freelancer.com",
            url="https://developers.freelancer.com/",
            automation_level="api",
            required_env=["FREELANCER_ACCESS_TOKEN"],
            notes_ru="Есть developer API; подходит для международных заказов после регистрации.",
        ),
        IntegrationOption(
            name="FL.ru",
            url="https://www.fl.ru/rss/projects.xml",
            automation_level="discovery_only",
            required_env=[],
            notes_ru="Сейчас используется RSS для поиска; официальный канал автооткликов нужно подтверждать отдельно.",
        ),
        IntegrationOption(
            name="Kwork",
            url="https://kwork.com/for-sellers",
            automation_level="manual",
            required_env=[],
            notes_ru="Подходит для витрины услуг; без подтвержденного официального API не автоматизируем переписку.",
        ),
    ]


def payment_registry() -> list[IntegrationOption]:
    return [
        IntegrationOption(
            name="ЮKassa",
            url="https://yookassa.ru/developers/api",
            automation_level="api",
            required_env=["YOOKASSA_SHOP_ID", "YOOKASSA_SECRET_KEY"],
            notes_ru="API для приема платежей, webhooks и возвратов; нужен кабинет и договор/идентификация.",
        ),
        IntegrationOption(
            name="Платежи внутри биржи",
            url="",
            automation_level="platform_escrow",
            required_env=[],
            notes_ru="Предпочтительно для первых заказов: безопасная сделка и приемка внутри площадки.",
        ),
    ]


def build_setup_report(env: Mapping[str, str] | None = None) -> SetupReport:
    values = env or os.environ
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    if values.get("AUTO_MODE", "off").strip().lower() in {"draft", "autopilot"}:
        required.append("OPENAI_API_KEY")

    missing_required = [name for name in required if not values.get(name)]
    optional = []
    for item in [*marketplace_registry(), *payment_registry()]:
        optional.extend(item.required_env)
    missing_optional = sorted({name for name in optional if not values.get(name)})

    return SetupReport(
        ready_for_autopilot=not missing_required,
        missing_required=missing_required,
        missing_optional=missing_optional,
        marketplaces=marketplace_registry(),
        payments=payment_registry(),
    )


def format_setup_report(report: SetupReport) -> str:
    lines = [
        "Проверка готовности фриланс-агента",
        "",
        f"Автопилот: {'готов' if report.ready_for_autopilot else 'не готов'}",
    ]
    if report.missing_required:
        lines.extend(["", "Обязательные недостающие переменные:"])
        lines.extend(f"- {name}" for name in report.missing_required)
    if report.missing_optional:
        lines.extend(["", "Переменные для бирж и платежей:"])
        lines.extend(f"- {name}" for name in report.missing_optional)
    lines.extend(["", "Биржи:"])
    lines.extend(f"- {item.name}: {item.automation_level} - {item.notes_ru}" for item in report.marketplaces)
    lines.extend(["", "Платежи:"])
    lines.extend(f"- {item.name}: {item.automation_level} - {item.notes_ru}" for item in report.payments)
    return "\n".join(lines) + "\n"


def main() -> int:
    report = build_setup_report()
    print(format_setup_report(report))
    return 0 if report.ready_for_autopilot else 1


if __name__ == "__main__":
    raise SystemExit(main())
