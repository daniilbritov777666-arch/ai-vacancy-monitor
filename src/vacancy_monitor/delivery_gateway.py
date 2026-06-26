from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vacancy_monitor.config import Config


def build_delivery_gateway_url(*, base_url: str, order_id: str, filename: str) -> str:
    return f"{base_url.rstrip('/')}/{order_id}/{filename.lstrip('/')}"


def require_public_dir(public_dir: Path) -> Path:
    if public_dir.exists() and not public_dir.is_dir():
        raise RuntimeError(f"DELIVERY_PUBLIC_DIR is not a directory: {public_dir}")
    public_dir.mkdir(parents=True, exist_ok=True)
    return public_dir


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
