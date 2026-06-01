from vacancy_monitor.telegram import answer_callback_query, send_telegram_message


class Response:
    def raise_for_status(self):
        return None


def test_send_telegram_message_supports_reply_markup(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("vacancy_monitor.telegram.requests.post", fake_post)

    send_telegram_message(
        "token",
        "150761046",
        "Привет",
        reply_markup={
            "inline_keyboard": [[{"text": "Одобрить отклик", "callback_data": "order:approve_outreach:abc"}]]
        },
    )

    assert calls[0]["json"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Одобрить отклик"


def test_send_telegram_message_keeps_simple_call_shape(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("vacancy_monitor.telegram.requests.post", fake_post)

    send_telegram_message("token", "150761046", "Привет")

    assert "reply_markup" not in calls[0]["json"]
    assert calls[0]["json"]["text"] == "Привет"


def test_answer_callback_query_posts_to_api(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("vacancy_monitor.telegram.requests.post", fake_post)

    answer_callback_query("token", "callback-1", "Готово.")

    assert calls[0]["url"].endswith("/answerCallbackQuery")
    assert calls[0]["json"]["callback_query_id"] == "callback-1"
