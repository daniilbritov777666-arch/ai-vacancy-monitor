from __future__ import annotations

import requests


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()
