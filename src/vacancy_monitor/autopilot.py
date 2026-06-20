from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import requests

from vacancy_monitor.execution import ExecutionDraftPackage
from vacancy_monitor.freelancehunt import FreelancehuntThreadMessage
from vacancy_monitor.order_models import Order, OrderStatus, format_moscow_time
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.quality import AIQualityReview


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
    def __init__(self, *, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def analyze_order(self, order: Order) -> AutopilotResult:
        try:
            response = self._post_with_retry(
                lambda: requests.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "input": _build_input(order),
                        "text": {"format": _json_schema_format()},
                    },
                    timeout=60,
                )
            )
            response.raise_for_status()
            return _parse_autopilot_result(_extract_output_text(response.json()))
        except requests.HTTPError as exc:
            if not _should_fallback_to_chat(exc):
                raise
        return self._analyze_order_with_chat_completions(order)

    def draft_thread_reply(self, order: Order, messages: list[FreelancehuntThreadMessage]) -> str:
        try:
            response = self._post_with_retry(
                lambda: requests.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "input": _build_reply_input(order, messages),
                    },
                    timeout=60,
                )
            )
            response.raise_for_status()
            return _normalize_text(_extract_output_text(response.json()))
        except requests.HTTPError as exc:
            if not _should_fallback_to_chat(exc):
                raise
        return self._draft_thread_reply_with_chat_completions(order, messages)

    def draft_execution_package(
        self,
        order: Order,
        conversation_text: str,
        execution_context: str,
    ) -> ExecutionDraftPackage:
        try:
            response = self._post_with_retry(
                lambda: requests.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "input": _build_execution_input(order, conversation_text, execution_context),
                        "text": {"format": _execution_json_schema_format()},
                    },
                    timeout=90,
                )
            )
            response.raise_for_status()
            return _parse_execution_package(_extract_output_text(response.json()))
        except requests.HTTPError as exc:
            if not _should_fallback_to_chat(exc):
                raise
        return self._draft_execution_package_with_chat_completions(order, conversation_text, execution_context)

    def review_execution_package(
        self,
        order: Order,
        conversation_text: str,
        package: ExecutionDraftPackage,
    ) -> AIQualityReview:
        prompt = _build_quality_review_input(order, conversation_text, package)
        try:
            response = self._post_with_retry(
                lambda: requests.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "input": prompt,
                        "text": {"format": _quality_json_schema_format()},
                    },
                    timeout=90,
                )
            )
            response.raise_for_status()
            return _parse_quality_review(_extract_output_text(response.json()))
        except requests.HTTPError as exc:
            if not _should_fallback_to_chat(exc):
                raise
        response = self._post_with_retry(
            lambda: requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": prompt,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
                timeout=90,
            )
        )
        response.raise_for_status()
        return _parse_quality_review(_extract_chat_content(response.json()))

    def repair_execution_package(
        self,
        order: Order,
        conversation_text: str,
        package: ExecutionDraftPackage,
        repair_instructions_ru: str,
    ) -> ExecutionDraftPackage:
        prompt = _build_repair_input(order, conversation_text, package, repair_instructions_ru)
        try:
            response = self._post_with_retry(
                lambda: requests.post(
                    f"{self.base_url}/responses",
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "input": prompt,
                        "text": {"format": _execution_json_schema_format()},
                    },
                    timeout=90,
                )
            )
            response.raise_for_status()
            return _parse_execution_package(_extract_output_text(response.json()))
        except requests.HTTPError as exc:
            if not _should_fallback_to_chat(exc):
                raise
        response = self._post_with_retry(
            lambda: requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": prompt,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=90,
            )
        )
        response.raise_for_status()
        return _parse_execution_package(_extract_chat_content(response.json()))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _analyze_order_with_chat_completions(self, order: Order) -> AutopilotResult:
        response = self._post_with_retry(
            lambda: requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": _build_chat_messages(order),
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=60,
            )
        )
        response.raise_for_status()
        return _parse_autopilot_result(_extract_chat_content(response.json()))

    def _draft_thread_reply_with_chat_completions(self, order: Order, messages: list[FreelancehuntThreadMessage]) -> str:
        prompt = _build_reply_input(order, messages)
        response = self._post_with_retry(
            lambda: requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": prompt,
                    "temperature": 0.2,
                },
                timeout=60,
            )
        )
        response.raise_for_status()
        return _normalize_text(_extract_chat_content(response.json()))

    def _draft_execution_package_with_chat_completions(
        self,
        order: Order,
        conversation_text: str,
        execution_context: str,
    ) -> ExecutionDraftPackage:
        prompt = _build_execution_chat_messages(order, conversation_text, execution_context)
        response = self._post_with_retry(
            lambda: requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": prompt,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=90,
            )
        )
        response.raise_for_status()
        return _parse_execution_package(_extract_chat_content(response.json()))

    def _post_with_retry(self, send: Callable[[], requests.Response]) -> requests.Response:
        last_exc: requests.RequestException | None = None
        for _ in range(2):
            try:
                return send()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("AI request did not run")


def run_order_autopilot(
    *,
    order: Order,
    store: OrderStore,
    result: AutopilotResult,
    max_price_rub: int,
    mode: str,
) -> Order:
    result = _result_with_budget_fallback(order, result)
    order_dir = store.order_dir(order.order_id)
    _write_autopilot_files(order_dir, result)

    if (
        mode == "autopilot"
        and result.safe_to_autopilot
        and 0 < result.price_rub <= max_price_rub
    ):
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

    updated = replace(
        order,
        status=OrderStatus.SKIPPED if mode == "autopilot" else order.status,
        price_rub=result.price_rub or order.price_rub,
        deadline_ru=result.deadline_ru or order.deadline_ru,
        risks=result.risk_flags,
        updated_at=format_moscow_time(),
    )
    store.save_order(updated)
    return updated


def _result_with_budget_fallback(order: Order, result: AutopilotResult) -> AutopilotResult:
    if result.price_rub > 0:
        return result
    fallback_price = _extract_budget_rub(order.original_text)
    if fallback_price <= 0:
        return result
    return replace(result, price_rub=fallback_price)


def _extract_budget_rub(text: str) -> int:
    compact = text.lower().replace("\xa0", " ")
    patterns = [
        (r"(\d[\d\s]*)\s*(?:₽|руб|р\.)", 1),
        (r"(\d[\d\s]*)\s*(?:uah|грн|₴)", 2),
        (r"(\d[\d\s]*)\s*(?:usd|\$)", 90),
        (r"(\d[\d\s]*)\s*(?:eur|€)", 100),
        (r"(\d[\d\s]*)\s*(?:pln|zł)", 22),
    ]
    for pattern, rate in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        amount = int(re.sub(r"\D", "", match.group(1)) or "0")
        return _round_price_rub(amount * rate)
    return 0


def _round_price_rub(value: int) -> int:
    if value <= 0:
        return 0
    if value < 1000:
        return value
    return (value // 100) * 100


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


def _parse_autopilot_result(raw_text: str) -> AutopilotResult:
    payload = json.loads(raw_text)
    payload["risk_flags"] = _normalize_string_list(payload.get("risk_flags", []))
    for field in (
        "summary_ru",
        "outreach_ru",
        "execution_plan_ru",
        "deadline_ru",
        "deliverable_markdown",
        "customer_message_ru",
    ):
        payload[field] = _normalize_text(payload.get(field, ""))
    payload["price_rub"] = int(payload.get("price_rub") or 0)
    payload["safe_to_autopilot"] = bool(payload.get("safe_to_autopilot"))
    return AutopilotResult(**payload)


def _parse_execution_package(raw_text: str) -> ExecutionDraftPackage:
    payload = json.loads(raw_text)
    files = payload.get("files") or {}
    if not isinstance(files, dict):
        files = {}
    return ExecutionDraftPackage(
        summary_ru=_normalize_text(payload.get("summary_ru", "")),
        files={str(name): _normalize_text(content) for name, content in files.items()},
        delivery_message_ru=_normalize_text(payload.get("delivery_message_ru", "")),
    )


def _parse_quality_review(raw_text: str) -> AIQualityReview:
    payload = json.loads(raw_text)
    return AIQualityReview(
        passed=bool(payload.get("passed")),
        issues=tuple(_normalize_string_list(payload.get("issues", []))),
        repair_instructions_ru=_normalize_text(payload.get("repair_instructions_ru", "")),
    )


def _normalize_text(value: object) -> str:
    if isinstance(value, list):
        lines = []
        for index, item in enumerate(value, start=1):
            text = str(item).strip()
            if text:
                lines.append(f"{index}. {text}")
        return "\n".join(lines)
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


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


def _build_chat_messages(order: Order) -> list[dict]:
    messages = _build_input(order)
    return [
        messages[0],
        {
            "role": "user",
            "content": (
                f"{messages[1]['content']}\n\n"
                "Верни только валидный JSON-объект без Markdown. Обязательные ключи: "
                "safe_to_autopilot, risk_flags, summary_ru, outreach_ru, execution_plan_ru, "
                "price_rub, deadline_ru, deliverable_markdown, customer_message_ru."
            ),
        },
    ]


def _build_reply_input(order: Order, messages: list[FreelancehuntThreadMessage]) -> list[dict]:
    transcript = "\n".join(
        f"{'Мы' if message.is_own else 'Заказчик'}"
        f"{' (' + message.created_at + ')' if message.created_at else ''}: {message.text}"
        for message in messages
        if message.text
    )
    return [
        {
            "role": "system",
            "content": (
                "Ты помощник фрилансера по разовым IT-заказам. Пиши коротко, по-русски, деловым тоном. "
                "Не обещай оплату вне безопасной сделки, не проси пароли в переписке, не соглашайся на серые задачи. "
                "Если не хватает данных, задай 1-3 конкретных вопроса. Не используй Markdown."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Заказ: {order.category}\n"
                f"Ссылка: {order.source_url}\n"
                f"Исходное ТЗ:\n{order.original_text}\n\n"
                f"История переписки:\n{transcript or '[нет сообщений]'}\n\n"
                "Подготовь ответ заказчику от первого лица. Текст должен быть готов к отправке."
            ),
        },
    ]


def _build_execution_input(order: Order, conversation_text: str, execution_context: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Ты исполнитель разовых IT-фриланс задач. Готовь практичный deliverable-пакет на русском. "
                "Не включай реальные секреты, токены, пароли, приватные ключи. "
                "Если данных не хватает, создай безопасный рабочий черновик и список уточнений. "
                "Файлы должны быть самодостаточными и не требовать опасных действий."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Категория: {order.category}\n"
                f"Источник: {order.source_url}\n\n"
                f"Исходное ТЗ:\n{order.original_text}\n\n"
                f"Переписка:\n{conversation_text or '[нет переписки]'}\n\n"
                f"Рабочий контекст:\n{execution_context or '[нет контекста]'}\n\n"
                "Верни JSON с ключами summary_ru, files, delivery_message_ru. "
                "files - объект имя_файла -> содержимое файла."
            ),
        },
    ]


def _build_execution_chat_messages(order: Order, conversation_text: str, execution_context: str) -> list[dict]:
    messages = _build_execution_input(order, conversation_text, execution_context)
    return [
        messages[0],
        {
            "role": "user",
            "content": (
                f"{messages[1]['content']}\n\n"
                "Верни только валидный JSON-объект без Markdown. Обязательные ключи: "
                "summary_ru, files, delivery_message_ru."
            ),
        },
    ]


def _build_quality_review_input(
    order: Order,
    conversation_text: str,
    package: ExecutionDraftPackage,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Ты строгий QA-рецензент результата разовой IT-задачи. Проверь соответствие ТЗ, "
                "полноту, работоспособность по статическому анализу, инструкции запуска и отсутствие секретов. "
                "Не считай обещания и описания заменой работающим файлам. Верни только структурированный JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Категория: {order.category}\nИсходное ТЗ:\n{order.original_text}\n\n"
                f"Переписка:\n{conversation_text or '[нет переписки]'}\n\n"
                f"Пакет результата:\n{_execution_package_text(package)}\n\n"
                "Верни passed, issues и repair_instructions_ru. passed=true только если пакет можно сдавать."
            ),
        },
    ]


def _build_repair_input(
    order: Order,
    conversation_text: str,
    package: ExecutionDraftPackage,
    repair_instructions_ru: str,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Ты исправляешь deliverable-пакет разовой IT-задачи после QA. "
                "Верни полный заменяющий пакет, без реальных секретов и без пояснений вне JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Категория: {order.category}\nИсходное ТЗ:\n{order.original_text}\n\n"
                f"Переписка:\n{conversation_text or '[нет переписки]'}\n\n"
                f"Текущий пакет:\n{_execution_package_text(package)}\n\n"
                f"Обязательные исправления:\n{repair_instructions_ru}\n\n"
                "Верни JSON с ключами summary_ru, files, delivery_message_ru. files содержит весь итоговый набор файлов."
            ),
        },
    ]


def _execution_package_text(package: ExecutionDraftPackage) -> str:
    return json.dumps(
        {
            "summary_ru": package.summary_ru,
            "files": package.files,
            "delivery_message_ru": package.delivery_message_ru,
        },
        ensure_ascii=False,
        indent=2,
    )[:200_000]


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


def _execution_json_schema_format() -> dict:
    return {
        "type": "json_schema",
        "name": "execution_draft_package",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary_ru": {"type": "string"},
                "files": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "delivery_message_ru": {"type": "string"},
            },
            "required": ["summary_ru", "files", "delivery_message_ru"],
            "additionalProperties": False,
        },
    }


def _quality_json_schema_format() -> dict:
    properties = {
        "passed": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "repair_instructions_ru": {"type": "string"},
    }
    return {
        "type": "json_schema",
        "name": "execution_quality_review",
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


def _extract_chat_content(payload: dict) -> str:
    choices = payload.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
    raise RuntimeError("Chat completions response did not contain message content")


def _should_fallback_to_chat(exc: requests.HTTPError) -> bool:
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) != 400:
        return False
    try:
        payload = response.json()
    except Exception:
        text = getattr(response, "text", "")
    else:
        error = payload.get("error") if isinstance(payload, dict) else None
        text = error.get("message", "") if isinstance(error, dict) else str(payload)
    return "chat/completions" in text
