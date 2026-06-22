from datetime import UTC, datetime, timedelta

from vacancy_monitor.job_queue import AgentJobQueue, JobStatus


NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)


def enqueue_order(queue: AgentJobQueue, order_id: str = "order-1", *, max_attempts: int = 4):
    return queue.enqueue(
        order_id=order_id,
        kind="advance_order",
        payload={"version": 1},
        idempotency_key=f"advance_order:{order_id}",
        max_attempts=max_attempts,
        now=NOW,
    )


def test_enqueue_is_idempotent(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")

    first = enqueue_order(queue)
    second = enqueue_order(queue)

    assert first.job_id == second.job_id
    assert first.status == JobStatus.PENDING
    assert queue.counts() == {"pending": 1}


def test_claim_next_leases_only_one_job_across_connections(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    first_queue = AgentJobQueue(path)
    second_queue = AgentJobQueue(path)
    enqueue_order(first_queue)

    claimed = first_queue.claim_next(lease_seconds=600, now=NOW)

    assert claimed is not None
    assert claimed.status == JobStatus.LEASED
    assert claimed.attempts == 1
    assert claimed.lease_until == NOW + timedelta(seconds=600)
    assert second_queue.claim_next(lease_seconds=600, now=NOW) is None


def test_complete_marks_job_succeeded(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    enqueue_order(queue)
    claimed = queue.claim_next(lease_seconds=600, now=NOW)
    assert claimed is not None

    completed = queue.complete(claimed.job_id, now=NOW + timedelta(seconds=2))

    assert completed.status == JobStatus.SUCCEEDED
    assert completed.completed_at == NOW + timedelta(seconds=2)
    assert completed.lease_until is None


def test_retry_delays_job_and_preserves_error(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    enqueue_order(queue)
    claimed = queue.claim_next(lease_seconds=600, now=NOW)
    assert claimed is not None

    retried = queue.retry(
        claimed.job_id,
        RuntimeError("temporary failure"),
        delay_seconds=60,
        now=NOW,
    )

    assert retried.status == JobStatus.PENDING
    assert retried.available_at == NOW + timedelta(seconds=60)
    assert retried.last_error_type == "RuntimeError"
    assert retried.last_error_message == "temporary failure"
    assert queue.claim_next(lease_seconds=600, now=NOW) is None
    assert queue.claim_next(lease_seconds=600, now=NOW + timedelta(seconds=60)) is not None


def test_fail_moves_job_to_dead(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    enqueue_order(queue)
    claimed = queue.claim_next(lease_seconds=600, now=NOW)
    assert claimed is not None

    failed = queue.fail(claimed.job_id, ValueError("invalid payload"), now=NOW)

    assert failed.status == JobStatus.DEAD
    assert failed.last_error_type == "ValueError"
    assert failed.completed_at == NOW
    assert queue.claim_next(lease_seconds=600, now=NOW) is None


def test_release_expired_leases_returns_job_to_pending(tmp_path):
    queue = AgentJobQueue(tmp_path / "jobs.sqlite3")
    enqueue_order(queue)
    claimed = queue.claim_next(lease_seconds=600, now=NOW)
    assert claimed is not None

    recovered = queue.release_expired_leases(now=NOW + timedelta(seconds=601))

    assert recovered == 1
    pending = queue.get(claimed.job_id)
    assert pending.status == JobStatus.PENDING
    assert pending.lease_until is None
    assert queue.claim_next(lease_seconds=600, now=NOW + timedelta(seconds=601)) is not None
