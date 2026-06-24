from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from vacancy_monitor.config import Config
from vacancy_monitor.order_models import MOSCOW_TZ
from datetime import datetime


Connector = Callable[[tuple[str, int], float], object]


@dataclass(frozen=True)
class EmailTransportHealth:
    checked_at: str
    status: str
    smtp_configured: bool
    imap_configured: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    smtp_reachable: bool = False
    imap_reachable: bool = False
    smtp_error: str | None = None
    imap_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def probe_email_transport(
    config: Config,
    *,
    connector: Connector | None = None,
    timeout_seconds: float = 3.0,
) -> EmailTransportHealth:
    smtp_configured = bool(config.smtp_host and config.smtp_from)
    imap_configured = bool(config.imap_host)
    connect = connector or socket.create_connection

    smtp_reachable = False
    smtp_error = None
    if smtp_configured and config.smtp_host:
        smtp_reachable, smtp_error = _probe_socket(
            connect=connect,
            host=config.smtp_host,
            port=config.smtp_port,
            timeout_seconds=timeout_seconds,
        )

    imap_reachable = False
    imap_error = None
    if imap_configured and config.imap_host:
        imap_reachable, imap_error = _probe_socket(
            connect=connect,
            host=config.imap_host,
            port=config.imap_port,
            timeout_seconds=timeout_seconds,
        )

    if smtp_configured and imap_configured and smtp_reachable and imap_reachable:
        status = "available"
    elif (smtp_configured and not smtp_reachable) or (imap_configured and not imap_reachable):
        status = "unavailable" if not smtp_reachable and not imap_reachable else "degraded"
    else:
        status = "degraded"

    return EmailTransportHealth(
        checked_at=datetime.now(tz=MOSCOW_TZ).isoformat(),
        status=status,
        smtp_configured=smtp_configured,
        imap_configured=imap_configured,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port if config.smtp_host else None,
        imap_host=config.imap_host,
        imap_port=config.imap_port if config.imap_host else None,
        smtp_reachable=smtp_reachable,
        imap_reachable=imap_reachable,
        smtp_error=smtp_error,
        imap_error=imap_error,
    )


def write_email_transport_health_report(path: Path, report: EmailTransportHealth) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
    return path


def _probe_socket(*, connect: Connector, host: str, port: int, timeout_seconds: float) -> tuple[bool, str | None]:
    try:
        connection = connect((host, port), timeout_seconds)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    close = getattr(connection, "close", None)
    if callable(close):
        close()
    return True, None
