from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import requests

from vacancy_monitor.order_models import Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore


@dataclass(frozen=True)
class AutopilotResult:
    safe_to_autopilot: bool
    risk_flags: list[str]
    summary_ru: str
    outreach_ru: str
    execution_plan_ru: str
    price_rub: int
    deadline_ru: str
    deliverable_markdown: str
    customer_message_ru: str


class OpenAIResponsesClient:
    def __init__(self, *, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def analyze_order(self, order: Order) -> AutopilotResult:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": _build_input(order),
                "text": {"format": _json_schema_format()},
            },
            timeout=60,
        )
        response.raise_for_status()
        return AutopilotResult(**json.loads(_extract_output_text(response.json())))


def run_order_autopilot(
    *,
    order: Order,
    store: OrderStore,
    result: AutopilotResult,
    max_price_rub: int,
    mode: str,
) -> Order:
    order_dir = store.order_dir(order.order_id)
    _write_autopilot_files(order_dir, result)

    if mode == "autopilot" and result.safe_to_autopilot and result.price_rub <= max_price_rub:
        updated = replace(
            order,
            status=OrderStatus.DRAFT_READY,
            price_rub=result.price_rub,
            deadline_ru=result.deadline_ru,
            risks=result.risk_flags,
            updated_at=format_moscow_time(),
        )
        store.save_order(updated)
        return updated

    updated = replace(order, risks=result.risk_flags, updated_at=format_moscow_time())
    store.save_order(updated)
    return updated


def _write_autopilot_files(order_dir: Path, result: AutopilotResult) -> None:
    autopilot_dir = order_dir / "autopilot"
    deliverables_dir = order_dir / "deliverables"
    outbox_dir = order_dir / "outbox"
    autopilot_dir.mkdir(parents=True, exist_ok=True)
    deliverables_dir.mkdir(parents=True, exist_ok=True)
    outbox_dir.mkdir(parents=True, exist_ok=True)

    (autopilot_dir / "analysis.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (autopilot_dir / "outreach.md").write_text(result.outreach_ru.strip() + "\n", encoding="utf-8")
    (autopilot_dir / "execution_plan.md").write_text(result.execution_plan_ru.strip() + "\n", encoding="utf-8")
    (deliverables_dir / "autopilot_result.md").write_text(
        (result.deliverable_markdown or "# Черновик результата\n\nТребуются уточнения.").strip() + "\n",
        encoding="utf-8",
    )
    (outbox_dir / "customer_message.md").write_text(result.customer_message_ru.strip() + "\n", encoding="utf-8")


def _build_input(order: Order) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Ты автономный помощник для разовых IT-фриланс заказов в РФ. "
                "Пиши по-русски. Не бери серые задачи, обходы лимитов, массовые аккаунты, "
                "накрутки, фишинг, вредоносное ПО и незаконный сбор персональных данных. "
                "Не обещай срок меньше 24 часов."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Категория: {order.category}\n"
                f"Источник: {order.source_url}\n"
                f"Текст заказа:\n{order.original_text}\n\n"
                "Верни структурированный JSON: безопасность, риски, отклик, план, цену, срок, "
                "черновик результата и сообщение заказчику."
            ),
        },
    ]


def _json_schema_format() -> dict:
    properties = {
        "safe_to_autopilot": {"type": "boolean"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "summary_ru": {"type": "string"},
        "outreach_ru": {"type": "string"},
        "execution_plan_ru": {"type": "string"},
        "price_rub": {"type": "integer"},
        "deadline_ru": {"type": "string"},
        "deliverable_markdown": {"type": "string"},
        "customer_message_ru": {"type": "string"},
    }
    return {
        "type": "json_schema",
        "name": "autopilot_order_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def _extract_output_text(payload: dict) -> str:
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and "text" in content:
                return content["text"]
    if "output_text" in payload:
        return payload["output_text"]
    raise RuntimeError("OpenAI response did not contain output_text")
