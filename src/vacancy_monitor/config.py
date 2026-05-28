from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CHANNELS = [
    "mari_vakansii",
    "digitaltender",
    "FreeVacanciesIT",
]


@dataclass(frozen=True)
class Config:
    bot_token: str
    chat_id: str
    channels: list[str]
    state_path: Path
    send_first_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        channels = _csv(os.environ.get("TELEGRAM_CHANNELS")) or DEFAULT_CHANNELS
        state_path = Path(os.environ.get("STATE_PATH", "data/seen_posts.json"))
        send_first_run = os.environ.get("SEND_FIRST_RUN", "").lower() in {"1", "true", "yes"}

        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        if not chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is required")

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            channels=channels,
            state_path=state_path,
            send_first_run=send_first_run,
        )


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
