from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from vacancy_monitor.order_models import Order, format_moscow_time
from vacancy_monitor.order_store import OrderStore


@dataclass(frozen=True)
class DeliveryPayload:
    channel: str
    delivery_mode: str
    attachment_supported: bool
    message_text: str
    generated_files: list[str]
    manifest_path: str
    fallback_path: str
    instructions_ru: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_delivery_payload(*, store: OrderStore, order: Order, message_text: str) -> DeliveryPayload:
    order_dir = store.order_dir(order.order_id)
    manifest_path = _write_delivery_package_manifest(store=store, order=order)
    fallback_path = order_dir / "outbox" / "delivery_fallback.md"
    channel = _delivery_channel(order)
    payload = DeliveryPayload(
        channel=channel,
        delivery_mode=_delivery_mode(channel),
        attachment_supported=False,
        message_text=_with_package_note(message_text),
        generated_files=_generated_file_list(store=store, order=order),
        manifest_path=manifest_path.relative_to(order_dir).as_posix(),
        fallback_path=fallback_path.relative_to(order_dir).as_posix(),
        instructions_ru=(
            "Канал доставки сейчас отправляет текстовое сообщение. "
            "Файлы результата подготовлены в локальном пакете заказа; если площадка не поддерживает вложения, "
            "передайте архив/файлы внешним способом и сохраните receipt."
        ),
    )
    return payload


def _with_package_note(message_text: str) -> str:
    text = message_text.strip()
    if "Пакет результата" in text:
        return text
    return (
        f"{text}\n\n"
        "Пакет результата подготовлен. Если в этом канале вложения не отобразятся, "
        "передам файлы удобным способом или архивом."
    )


def _delivery_channel(order: Order) -> str:
    if order.contact and order.contact.channel:
        return order.contact.channel
    return "manual"


def _delivery_mode(channel: str) -> str:
    if channel == "freelancehunt":
        return "thread_message"
    if channel == "email":
        return "email_message"
    return "manual_message"


def _generated_file_list(*, store: OrderStore, order: Order) -> list[str]:
    order_dir = store.order_dir(order.order_id)
    generated_dir = order_dir / "execution" / "generated"
    if not generated_dir.exists():
        return []
    return [
        path.relative_to(order_dir).as_posix()
        for path in sorted(generated_dir.rglob("*"))
        if path.is_file()
    ]


def _delivery_quality_summary(*, store: OrderStore, order: Order) -> dict:
    path = store.order_dir(order.order_id) / "quality" / "latest.json"
    if not path.exists():
        return {"passed": None, "report": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passed": False, "report": "quality/latest.json"}
    return {
        "passed": bool(payload.get("passed")),
        "report": "quality/latest.json",
    }


def _write_delivery_package_manifest(*, store: OrderStore, order: Order):
    order_dir = store.order_dir(order.order_id)
    outbox_dir = order_dir / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / "delivery_package_manifest.json"
    payload = {
        "created_at": format_moscow_time(),
        "order_id": order.order_id,
        "generated_files": _generated_file_list(store=store, order=order),
        "delivery_message": "outbox/delivery_message.md",
        "quality": _delivery_quality_summary(store=store, order=order),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (outbox_dir / "delivery_fallback.md").write_text(
        (
            "# Fallback отправки результата\n\n"
            "Если канал площадки не поддерживает вложения, передайте заказчику файлы из `execution/generated/` "
            "и текст из `outbox/delivery_message.md`, затем сохраните внешний receipt в папке заказа.\n"
        ),
        encoding="utf-8",
    )
    return path
