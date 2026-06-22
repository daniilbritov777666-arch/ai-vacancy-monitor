import json
from datetime import UTC, datetime

import pytest
import requests

from vacancy_monitor.job_queue import AgentJobQueue
from vacancy_monitor.job_worker import (
    is_retryable_job_error,
    retry_delay_seconds,
    write_dead_letter,
    write_job_attempt,
    write_queue_health,
)


NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)


def http_error(status_code: int) -> requests.HTTPError:
    error = requests.HTTPError(f"{status_code} Client Error")
    error.response = type("Response", (), {"status_code": status_code})()
    return error


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("timeout"),
        requests.ConnectionError("offline"),
        http_error(408),
        http_error(429),
        http_error(500),
        http_error(503),
    ],
)
def test_retryable_job_errors(error):
    assert is_retryable_job_error(error) is True


@pytest.mark.parametrize(
    "error",
    [ValueError("invalid"), http_error(400), http_error(401), http_error(403), http_error(404), http_error(410), http_error(422)],
)
def test_terminal_job_errors(error):
    assert is_retryable_job_error(error) is False


def test_retry_delay_is_bounded_and_deterministic():
    for attempts, base in [(1, 60), (2, 300), (3, 900)]:
        first = retry_delay_seconds(attempts, "job-1")
        second = retry_delay_seconds(attempts, "job-1")
        assert first == second
        assert base <= first <= int(base * 1.1)


def test_job_attempt_and_dead_letter_are_secret_safe(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    job = queue.enqueue(
        order_id="order-1",
        kind="advance_order",
        payload={"version": 1},
        idempotency_key="advance_order:order-1",
        max_attempts=4,
        now=NOW,
    )
    error = RuntimeError("x" * 300)
    order_dir = tmp_path / "orders" / "order-1"

    write_job_attempt(order_dir=order_dir, job=job, outcome="retry", error=error, now=NOW)
    write_dead_letter(order_dir=order_dir, job=job, error=error, now=NOW)

    attempt = json.loads((order_dir / "jobs" / f"{job.job_id}.json").read_text(encoding="utf-8"))
    dead = json.loads((order_dir / "jobs" / "dead.json").read_text(encoding="utf-8"))
    assert attempt["attempts"][0]["error_type"] == "RuntimeError"
    assert len(attempt["attempts"][0]["error_message"]) == 200
    assert dead["job_id"] == job.job_id
    assert "payload" not in dead


def test_queue_health_report_contains_counts(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    queue.enqueue(
        order_id="order-1",
        kind="advance_order",
        payload={"version": 1},
        idempotency_key="advance_order:order-1",
        max_attempts=4,
        now=NOW,
    )
    path = tmp_path / "reports" / "job_queue_health.json"

    write_queue_health(path=path, queue=queue, recovered_leases=2, now=NOW)

    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["counts"] == {"pending": 1}
    assert report["recovered_leases"] == 2
    assert report["oldest_pending_at"] == NOW.isoformat()
