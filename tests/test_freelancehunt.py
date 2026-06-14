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

    def post(self, url, headers, json, timeout):
        self.calls.append(
            {
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
