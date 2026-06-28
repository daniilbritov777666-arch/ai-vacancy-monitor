from vacancy_monitor.freelancehunt import FreelancehuntBid, FreelancehuntClient, build_bid_preflight


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
        if url.endswith("/my/profile"):
            return FakeResponse(
                {
                    "data": {
                        "id": 1965999,
                        "type": "freelancer",
                        "attributes": {
                            "login": "daniilbritov",
                            "is_plus_active": False,
                            "status": {"id": 10, "name": "Свободен для работы"},
                            "verification": {
                                "identity": False,
                                "birth_date": False,
                                "phone": False,
                                "email": True,
                            },
                        },
                    }
                },
                status_code=200,
            )
        if "/projects/" in url:
            return FakeResponse(
                {
                    "data": {
                        "id": 1638234,
                        "type": "project",
                        "attributes": {
                            "status": {"id": 11, "name": "Open for proposals"},
                            "safe_type": "employer",
                            "budget": {"amount": 4000, "currency": "UAH"},
                            "expired_at": "2026-07-12T13:28:31+03:00",
                            "freelancer": None,
                        },
                    }
                },
                status_code=200,
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
        if url.endswith("/my/bids"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "id": "bid-1",
                            "attributes": {
                                "status": "active",
                                "is_winner": True,
                                "project": {
                                    "id": 123456,
                                    "status": {"id": 21, "name": "completed"},
                                },
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


def test_freelancehunt_client_lists_my_bids_with_project_state():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    bids = client.list_my_bids()

    assert len(bids) == 1
    assert bids[0].bid_id == "bid-1"
    assert bids[0].project_id == "123456"
    assert bids[0].status == "active"
    assert bids[0].is_winner is True
    assert bids[0].project_status == "completed"
    assert session.calls[0]["url"] == "https://api.freelancehunt.com/v2/my/bids"


def test_freelancehunt_client_reads_profile_and_project_for_bid_preflight():
    session = FakeSession()
    client = FreelancehuntClient(api_token="fh-token", session=session)

    profile = client.get_profile()
    project = client.get_project("1638234")
    audit = build_bid_preflight(profile=profile, project=project)

    assert audit["eligible"] is True
    assert audit["profile"]["id"] == "1965999"
    assert audit["profile"]["verification"]["email"] is True
    assert audit["profile"]["verification"]["identity"] is False
    assert audit["project"]["id"] == "1638234"
    assert audit["project"]["status_id"] == 11
    assert audit["project"]["safe_type"] == "employer"
    assert audit["project"]["budget"] == {"amount": 4000, "currency": "UAH"}
    assert audit["warnings"] == [
        "profile_identity_not_verified",
        "profile_birth_date_not_verified",
        "profile_phone_not_verified",
    ]
    assert [call["url"] for call in session.calls] == [
        "https://api.freelancehunt.com/v2/my/profile",
        "https://api.freelancehunt.com/v2/projects/1638234",
    ]


def test_bid_preflight_blocks_closed_and_business_safe_projects():
    profile = {
        "data": {
            "id": 1,
            "type": "freelancer",
            "attributes": {"verification": {"identity": True, "birth_date": True, "phone": True, "email": True}},
        }
    }
    project = {
        "data": {
            "id": 2,
            "type": "project",
            "attributes": {
                "status": {"id": 13, "name": "Contractor chosen"},
                "safe_type": "employer_cashless",
                "freelancer": {"id": 99},
            },
        }
    }

    audit = build_bid_preflight(profile=profile, project=project)

    assert audit["eligible"] is False
    assert audit["blockers"] == [
        "project_not_open_for_proposals",
        "project_has_contractor",
        "business_safe_not_supported_by_api",
    ]


def test_bid_preflight_blocks_external_person_payment_type():
    profile = {
        "data": {
            "id": 1,
            "type": "freelancer",
            "attributes": {"verification": {"identity": True, "birth_date": True, "phone": True, "email": True}},
        }
    }
    project = {
        "data": {
            "id": 2,
            "type": "project",
            "attributes": {
                "status": {"id": 11, "name": "Open for proposals"},
                "safe_type": "person",
                "budget": {"amount": 200, "currency": "PLN"},
                "freelancer": None,
            },
        }
    }

    audit = build_bid_preflight(profile=profile, project=project)

    assert audit["eligible"] is False
    assert audit["blockers"] == ["unsupported_project_safe_type"]
    assert audit["project"]["budget"] == {"amount": 200, "currency": "PLN"}
