from __future__ import annotations

import re

TRYCLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def parse_trycloudflare_url(line: str) -> str | None:
    match = TRYCLOUDFLARE_URL_RE.search(line)
    return match.group(0) if match else None
