from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


@dataclass(frozen=True)
class AgentJob:
    job_id: str
    order_id: str
    kind: str
    payload: dict
    idempotency_key: str
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_until: datetime | None
    last_error_type: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AgentJobQueue:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def enqueue(
        self,
        *,
        order_id: str,
        kind: str,
        payload: dict,
        idempotency_key: str,
        max_attempts: int,
        now: datetime,
    ) -> AgentJob:
        timestamp = _iso(now)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    job_id, order_id, kind, payload_json, idempotency_key,
                    status, attempts, max_attempts, available_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    order_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    idempotency_key,
                    JobStatus.PENDING.value,
                    max_attempts,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _job_from_row(row)

    def claim_next(self, *, lease_seconds: int, now: datetime) -> AgentJob | None:
        timestamp = _iso(now)
        lease_until = _iso(now + timedelta(seconds=lease_seconds))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = ? AND available_at <= ?
                ORDER BY available_at, created_at, job_id
                LIMIT 1
                """,
                (JobStatus.PENDING.value, timestamp),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, attempts = attempts + 1, lease_until = ?, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    JobStatus.LEASED.value,
                    lease_until,
                    timestamp,
                    row["job_id"],
                    JobStatus.PENDING.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
            connection.commit()
            return _job_from_row(claimed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(self, job_id: str, *, now: datetime) -> AgentJob:
        return self._finish(job_id, status=JobStatus.SUCCEEDED, error=None, now=now)

    def fail(self, job_id: str, error: Exception, *, now: datetime) -> AgentJob:
        return self._finish(job_id, status=JobStatus.DEAD, error=error, now=now)

    def retry(
        self,
        job_id: str,
        error: Exception,
        *,
        delay_seconds: int,
        now: datetime,
    ) -> AgentJob:
        timestamp = _iso(now)
        available_at = _iso(now + timedelta(seconds=delay_seconds))
        error_type, error_message = _error_fields(error)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, available_at = ?, lease_until = NULL,
                    last_error_type = ?, last_error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.PENDING.value,
                    available_at,
                    error_type,
                    error_message,
                    timestamp,
                    job_id,
                ),
            )
        return self.get(job_id)

    def release_expired_leases(self, *, now: datetime) -> int:
        timestamp = _iso(now)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, lease_until = NULL, available_at = ?, updated_at = ?
                WHERE status = ? AND lease_until < ?
                """,
                (
                    JobStatus.PENDING.value,
                    timestamp,
                    timestamp,
                    JobStatus.LEASED.value,
                    timestamp,
                ),
            )
            return cursor.rowcount

    def get(self, job_id: str) -> AgentJob:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job_from_row(row)

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY status"
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def oldest_pending_at(self) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(created_at) AS created_at FROM jobs WHERE status = ?",
                (JobStatus.PENDING.value,),
            ).fetchone()
        return _parse_time(row["created_at"]) if row else None

    def _finish(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error: Exception | None,
        now: datetime,
    ) -> AgentJob:
        timestamp = _iso(now)
        error_type, error_message = _error_fields(error) if error else (None, None)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, lease_until = NULL, completed_at = ?, updated_at = ?,
                    last_error_type = ?, last_error_message = ?
                WHERE job_id = ?
                """,
                (status.value, timestamp, timestamp, error_type, error_message, job_id),
            )
        return self.get(job_id)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    available_at TEXT NOT NULL,
                    lease_until TEXT,
                    last_error_type TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_available
                    ON jobs(status, available_at, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _error_fields(error: Exception) -> tuple[str, str]:
    return type(error).__name__, str(error).strip()[:200]


def _job_from_row(row: sqlite3.Row) -> AgentJob:
    return AgentJob(
        job_id=row["job_id"],
        order_id=row["order_id"],
        kind=row["kind"],
        payload=json.loads(row["payload_json"]),
        idempotency_key=row["idempotency_key"],
        status=JobStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        available_at=_parse_time(row["available_at"]),
        lease_until=_parse_time(row["lease_until"]),
        last_error_type=row["last_error_type"],
        last_error_message=row["last_error_message"],
        created_at=_parse_time(row["created_at"]),
        updated_at=_parse_time(row["updated_at"]),
        completed_at=_parse_time(row["completed_at"]),
    )
