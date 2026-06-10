import json

from vacancy_monitor.autopilot import (
    AutopilotResult,
    OpenAIResponsesClient,
    run_order_autopilot,
)
from vacancy_monitor.models import Post
from vacancy_monitor.order_models import OrderStatus, make_order_from_post
from vacancy_monitor.order_store import OrderStore
from vacancy_monitor.workspace import create_order_workspace


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def make_order():
    post = Post(
        source="sample",
        post_id="sample/1",
        url="https://example.com/project/1",
        text="Нужен Telegram-бот для приема заявок и записи в Google Sheets. Бюджет 12000 руб.",
        published_at="2026-06-04T12:00:00+03:00",
    )
    return make_order_from_post(post, category="Telegram-боты", risks=[])


def safe_payload():
    data = {
        "safe_to_autopilot": True,
        "risk_flags": [],
        "summary_ru": "Нужен бот для приема заявок.",
        "outreach_ru": "Здравствуйте! Готов выполнить бота для заявок.",
        "execution_plan_ru": "1. Уточнить поля заявки. 2. Собрать бота. 3. Проверить запись в таблицу.",
        "price_rub": 12000,
        "deadline_ru": "2 дня",
        "deliverable_markdown": "# Черновик результата\n\nПлан бота и структура таблицы.",
        "customer_message_ru": "Здравствуйте! Подготовил план и могу приступить.",
    }
    return {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(data, ensure_ascii=False),
                    }
                ]
            }
        ]
    }


def test_openai_responses_client_sends_schema_payload(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response(safe_payload())

    monkeypatch.setattr("vacancy_monitor.autopilot.requests.post", fake_post)
    client = OpenAIResponsesClient(api_key="sk-test", model="gpt-test")

    result = client.analyze_order(make_order())

    assert isinstance(result, AutopilotResult)
    assert result.safe_to_autopilot is True
    assert calls[0]["url"].endswith("/v1/responses")
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["json"]["model"] == "gpt-test"
    assert calls[0]["json"]["text"]["format"]["type"] == "json_schema"


def test_run_order_autopilot_writes_files_and_moves_safe_order_to_draft_ready(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order()
    store.save_order(order)
    create_order_workspace(store.orders_dir, order)
    result = AutopilotResult(
        safe_to_autopilot=True,
        risk_flags=[],
        summary_ru="Нужен бот для приема заявок.",
        outreach_ru="Здравствуйте! Готов выполнить бота.",
        execution_plan_ru="Собрать бота и таблицу.",
        price_rub=12000,
        deadline_ru="2 дня",
        deliverable_markdown="# Черновик результата",
        customer_message_ru="Готов приступить.",
    )

    updated = run_order_autopilot(order=order, store=store, result=result, max_price_rub=15000, mode="autopilot")

    order_dir = store.order_dir(order.order_id)
    assert updated.status == OrderStatus.DRAFT_READY
    assert (order_dir / "autopilot" / "analysis.json").exists()
    assert (order_dir / "autopilot" / "outreach.md").read_text(encoding="utf-8")
    assert (order_dir / "deliverables" / "autopilot_result.md").exists()
    assert (order_dir / "outbox" / "customer_message.md").exists()


def test_run_order_autopilot_keeps_unsafe_order_waiting_for_approval(tmp_path):
    store = OrderStore(tmp_path / "orders")
    order = make_order()
    store.save_order(order)
    create_order_workspace(store.orders_dir, order)
    result = AutopilotResult(
        safe_to_autopilot=False,
        risk_flags=["неясный объем"],
        summary_ru="Нужно уточнить объем.",
        outreach_ru="Здравствуйте! Нужно уточнить детали.",
        execution_plan_ru="Сначала задать вопросы.",
        price_rub=20000,
        deadline_ru="неясно",
        deliverable_markdown="",
        customer_message_ru="Уточните детали.",
    )

    updated = run_order_autopilot(order=order, store=store, result=result, max_price_rub=15000, mode="autopilot")

    assert updated.status == OrderStatus.AWAITING_RESPONSE_APPROVAL
    assert store.load_order(order.order_id).status == OrderStatus.AWAITING_RESPONSE_APPROVAL
