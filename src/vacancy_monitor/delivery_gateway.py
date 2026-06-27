from __future__ import annotations

import functools
import json
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from vacancy_monitor.config import Config


class DeliveryReadinessError(RuntimeError):
    pass


def build_delivery_gateway_url(*, base_url: str, order_id: str, filename: str) -> str:
    return f"{base_url.rstrip('/')}/{order_id}/{filename.lstrip('/')}"


def require_public_dir(public_dir: Path) -> Path:
    if public_dir.exists() and not public_dir.is_dir():
        raise RuntimeError(f"DELIVERY_PUBLIC_DIR is not a directory: {public_dir}")
    public_dir.mkdir(parents=True, exist_ok=True)
    return public_dir


def verify_public_archive(
    *,
    public_url: str,
    archive_path: Path,
    report_path: Path,
    timeout_seconds: float = 10,
    requester=requests.head,
) -> dict:
    expected_bytes = archive_path.stat().st_size
    report = {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "public_url": public_url,
        "archive": str(archive_path),
        "expected_bytes": expected_bytes,
        "ready": False,
    }
    try:
        if not public_url:
            report["error_type"] = "MissingPublicUrl"
            raise DeliveryReadinessError("публичная ссылка на архив не создана")
        response = requester(
            public_url,
            headers={"User-Agent": "vacancy-agent-delivery-check/1"},
            timeout=timeout_seconds,
            allow_redirects=True,
        )
        status_code = int(response.status_code)
        remote_length = response.headers.get("Content-Length")
        remote_bytes = int(remote_length) if remote_length is not None else None
        report.update(status_code=status_code, remote_bytes=remote_bytes)
        if status_code != 200:
            report["error_type"] = "UnexpectedStatus"
            raise DeliveryReadinessError(f"публичный архив недоступен: HTTP {status_code}")
        if remote_bytes is not None and remote_bytes != expected_bytes:
            report["error_type"] = "ContentLengthMismatch"
            raise DeliveryReadinessError("размер публичного архива не совпадает с локальным")
        report["ready"] = True
        _write_readiness_report(report_path, report)
        return report
    except DeliveryReadinessError:
        _write_readiness_report(report_path, report)
        raise
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        _write_readiness_report(report_path, report)
        raise DeliveryReadinessError("публичный архив недоступен") from exc


def _write_readiness_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def serve_delivery_public_dir(*, public_dir: Path, host: str, port: int) -> None:
    root = require_public_dir(public_dir)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    config = Config.from_env()
    if not config.delivery_gateway_enabled:
        raise RuntimeError("DELIVERY_GATEWAY_ENABLED is not true")
    if config.delivery_public_dir is None:
        raise RuntimeError("DELIVERY_PUBLIC_DIR is required")
    serve_delivery_public_dir(
        public_dir=config.delivery_public_dir,
        host=config.delivery_gateway_host,
        port=config.delivery_gateway_port,
    )


if __name__ == "__main__":
    main()
