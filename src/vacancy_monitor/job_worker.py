from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import requests

from vacancy_monitor.job_queue import AgentJob, AgentJobQueue


def is_retryable_job_error(error: Exception) -> bool:
    if isinstance(error, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(error, requests.HTTPError):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code in {408, 429} or bool(status_code and 500 <= status_code <= 599)
    return False


def retry_delay_seconds(attempts: int, job_id: str) -> int:
    base_delays = (60, 300, 900)
    base = base_delays[min(max(attempts, 1), len(base_delays)) - 1]
    digest = hashlib.sha256(f"{job_id}:{attempts}".encode("utf-8")).digest()
    jitter = digest[0] % (max(1, base // 10) + 1)
    return base + jitter


def write_job_attempt(
    *,
    order_dir: Path,
    job: AgentJob,
    outcome: str,
    error: Exception | None,
    now: datetime,
) -> None:
    path = order_dir / "jobs" / f"{job.job_id}.json"
    current = _read_json(path) if path.exists() else {
        "job_id": job.job_id,
        "order_id": job.order_id,
        "kind": job.kind,
        "attempts": [],
    }
    record = {
        "attempt": job.attempts,
        "time": now.isoformat(),
        "outcome": outcome,
    }
    if error is not None:
        record.update(_safe_error(error))
    current["attempts"].append(record)
    _write_json_atomic(path, current)


def write_dead_letter(
    *,
    order_dir: Path,
    job: AgentJob,
    error: Exception,
    now: datetime,
) -> None:
    payload = {
        "job_id": job.job_id,
        "order_id": job.order_id,
        "kind": job.kind,
        "attempts": job.attempts,
        "failed_at": now.isoformat(),
        **_safe_error(error),
    }
    _write_json_atomic(order_dir / "jobs" / "dead.json", payload)


def write_queue_health(
    *,
    path: Path,
    queue: AgentJobQueue,
    recovered_leases: int,
    now: datetime,
) -> None:
    oldest = queue.oldest_pending_at()
    payload = {
        "checked_at": now.isoformat(),
        "counts": queue.counts(),
        "recovered_leases": recovered_leases,
        "oldest_pending_at": oldest.isoformat() if oldest else None,
    }
    _write_json_atomic(path, payload)


def _safe_error(error: Exception) -> dict:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    payload = {
        "error_type": type(error).__name__,
        "error_message": str(error).strip()[:200],
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
