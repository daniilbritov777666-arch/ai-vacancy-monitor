from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CHANNELS: list[str] = []

DEFAULT_RSS_FEEDS = [
    "https://www.fl.ru/rss/projects.xml",
    "https://freelancehunt.com/projects.rss",
]


@dataclass(frozen=True)
class Config:
    bot_token: str
    chat_id: str
    channels: list[str]
    rss_feeds: list[str]
    state_path: Path
    send_first_run: bool
    orders_path: Path
    auto_mode: str = "off"
    auto_max_price_rub: int = 15000
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    freelancehunt_api_token: str | None = None
    freelancehunt_bid_safe_type: str = "employer"
    freelancehunt_bid_days: int = 2

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        channels = _csv(os.environ.get("TELEGRAM_CHANNELS")) or DEFAULT_CHANNELS
        rss_feeds = _csv(os.environ.get("RSS_FEEDS")) or DEFAULT_RSS_FEEDS
        state_path = Path(os.environ.get("STATE_PATH", "data/seen_posts.json"))
        send_first_run = os.environ.get("SEND_FIRST_RUN", "").lower() in {"1", "true", "yes"}
        orders_path = Path(os.environ.get("ORDERS_PATH", "orders"))
        auto_mode = os.environ.get("AUTO_MODE", "off").strip().lower()
        auto_max_price_rub = int(os.environ.get("AUTO_MAX_PRICE_RUB", "15000"))
        openai_model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
        openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None
        freelancehunt_api_token = os.environ.get("FREELANCEHUNT_API_TOKEN", "").strip() or None
        freelancehunt_bid_safe_type = os.environ.get("FREELANCEHUNT_BID_SAFE_TYPE", "employer").strip()
        freelancehunt_bid_days = int(os.environ.get("FREELANCEHUNT_BID_DAYS", "2"))

        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        if not chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is required")
        if auto_mode not in {"off", "draft", "autopilot"}:
            raise RuntimeError("AUTO_MODE must be off, draft, or autopilot")
        if freelancehunt_bid_safe_type not in {"employer", "developer", "split", "employer_cashless"}:
            raise RuntimeError("FREELANCEHUNT_BID_SAFE_TYPE must be employer, developer, split, or employer_cashless")

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            channels=channels,
            rss_feeds=rss_feeds,
            state_path=state_path,
            send_first_run=send_first_run,
            orders_path=orders_path,
            auto_mode=auto_mode,
            auto_max_price_rub=auto_max_price_rub,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            freelancehunt_api_token=freelancehunt_api_token,
            freelancehunt_bid_safe_type=freelancehunt_bid_safe_type,
            freelancehunt_bid_days=freelancehunt_bid_days,
        )


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
