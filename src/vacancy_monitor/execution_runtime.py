from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


def write_execution_runtime_health(
    *,
    path: Path,
    python_image: str,
    node_image: str,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    now: datetime | None = None,
) -> dict:
    run = runner or _run
    checked_at = now or datetime.now(tz=UTC)
    payload = {
        "checked_at": checked_at.isoformat(),
        "available": False,
        "client_version": None,
        "server_version": None,
        "images": {python_image: False, node_image: False},
    }
    try:
        version = run(
            ["docker", "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"],
            timeout=15,
        )
        if version.returncode != 0:
            raise RuntimeError("docker daemon unavailable")
        client, server = (version.stdout or "|").strip().split("|", 1)
        payload["client_version"] = client
        payload["server_version"] = server
        for image in (python_image, node_image):
            inspected = run(["docker", "image", "inspect", image], timeout=15)
            payload["images"][image] = inspected.returncode == 0
        payload["available"] = bool(client and server and all(payload["images"].values()))
    except Exception as exc:
        payload["error"] = type(exc).__name__
    _write_json_atomic(path, payload)
    return payload


def _run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, timeout=timeout, capture_output=True, text=True, check=False)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
