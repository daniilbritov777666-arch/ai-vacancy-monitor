from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


API_BASE_URL = "https://api.freelancehunt.com/v2"


@dataclass(frozen=True)
class FreelancehuntBid:
    days: int
    amount_rub: int
    comment: str
    safe_type: str = "employer"
    is_hidden: bool = False


class FreelancehuntClient:
    def __init__(self, *, api_token: str, session: Any = requests, base_url: str = API_BASE_URL):
        self.api_token = api_token
        self.session = session
        self.base_url = base_url.rstrip("/")

    def add_bid(self, *, project_id: str, bid: FreelancehuntBid) -> dict:
        response = self.session.post(
            f"{self.base_url}/projects/{project_id}/bids",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "Accept-Language": "ru",
                "Content-Type": "application/json",
            },
            json={
                "days": bid.days,
                "safe_type": bid.safe_type,
                "budget": {"amount": bid.amount_rub, "currency": "RUB"},
                "comment": bid.comment,
                "is_hidden": bid.is_hidden,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
