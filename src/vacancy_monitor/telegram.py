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


def get_updates(bot_token: str, *, offset: int | None = None, timeout_seconds: int = 20) -> list[dict]:
    params = {"timeout": timeout_seconds, "allowed_updates": ["callback_query"]}
    if offset is not None:
        params["offset"] = offset
    response = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params=params,
        timeout=timeout_seconds + 5,
    )
    response.raise_for_status()
    return response.json().get("result", [])
