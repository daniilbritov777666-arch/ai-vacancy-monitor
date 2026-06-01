from __future__ import annotations

import requests


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json=payload,
        timeout=20,
    )
    response.raise_for_status()


def answer_callback_query(bot_token: str, callback_query_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text[:200], "show_alert": False},
        timeout=20,
    )
    response.raise_for_status()
