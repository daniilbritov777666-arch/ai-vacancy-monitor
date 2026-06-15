from vacancy_monitor.freelancehunt import FreelancehuntBid, FreelancehuntClient


class FakeResponse:
    def __init__(self, payload, status_code=201):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if url.endswith("/threads"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "id": "thread-1",
                            "attributes": {
                                "subject": "Telegram bot",
                                "is_read": False,
                                "updated_at": "2026-06-15T09:00:00+03:00",
                            },
                            "relationships": {
                                "project": {"data": {"id": "123456"}},
                            },
                        }
                    ]
                },
                status_code=200,
            )
        return FakeResponse(
            {
                "data": [
                    {
                        "id": "msg-1",
                        "attributes": {
                            "message_html": "<p>Здравствуйте, когда сможете начать?</p>",
                            "created_at": "2026-06-15T09:02:00+03:00",
                            "is_own": False,
                        },
                    }
                ]
            },
            status_code=200,
        )

    def post(self, url, headers, json, timeout):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse({"data": {"id": 3140007, "type": "bid"}})


def test_freelancehunt_client_adds_project_bid():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    payload = client.add_bid(
        project_id="299172",
        bid=FreelancehuntBid(
            days=2,
            amount_rub=12000,
            comment="Здравствуйте! Готов выполнить задачу.",
            safe_type="employer",
        ),
    )

    assert payload["data"]["id"] == 3140007
    assert session.calls == [
        {
            "url": "https://api.freelancehunt.com/v2/projects/299172/bids",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer fh-token",
                "Accept": "application/json",
                "Accept-Language": "ru",
                "Content-Type": "application/json",
            },
            "json": {
                "days": 2,
                "safe_type": "employer",
                "budget": {"amount": 12000, "currency": "RUB"},
                "comment": "Здравствуйте! Готов выполнить задачу.",
                "is_hidden": False,
            },
            "timeout": 30,
        }
    ]


def test_freelancehunt_client_lists_threads():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    threads = client.list_threads()

    assert len(threads) == 1
    assert threads[0].thread_id == "thread-1"
    assert threads[0].project_id == "123456"
    assert threads[0].is_unread is True
    assert session.calls[0]["url"] == "https://api.freelancehunt.com/v2/threads"


def test_freelancehunt_client_reads_thread_messages():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    messages = client.get_thread_messages("thread-1")

    assert len(messages) == 1
    assert messages[0].message_id == "msg-1"
    assert messages[0].text == "Здравствуйте, когда сможете начать?"
    assert messages[0].is_own is False
    assert session.calls[0]["url"] == "https://api.freelancehunt.com/v2/threads/thread-1"


def test_freelancehunt_client_adds_thread_message():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    client.add_thread_message(thread_id="thread-1", message_html="Здравствуйте! Начать могу сегодня.")

    assert session.calls[0]["url"] == "https://api.freelancehunt.com/v2/threads/thread-1"
    assert session.calls[0]["json"] == {"message_html": "Здравствуйте! Начать могу сегодня."}
