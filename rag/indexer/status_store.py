"""SQLite-backed index job status records."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    workspace_id: str
    source_id: str
    mode: str
    idempotency_key: str
    status: JobStatus
    created_at: float
    updated_at: float
    lease_expires_at: float | None = None
    error: str | None = None
    result_json: str | None = None

    def result(self) -> dict[str, Any] | None:
        if not self.result_json:
            return None
        return json.loads(self.result_json)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["result"] = self.result()
        data.pop("result_json", None)
        return data


class StatusStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    lease_expires_at REAL,
                    error TEXT,
                    result_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
                ON jobs(workspace_id, source_id, idempotency_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_active
                ON jobs(workspace_id, source_id, status)
                """
            )
            conn.commit()

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _row_to_job(row) if row else None

    def get_by_idempotency(
        self,
        *,
        workspace_id: str,
        source_id: str,
        idempotency_key: str,
    ) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE workspace_id = ? AND source_id = ? AND idempotency_key = ?
                """,
                (workspace_id, source_id, idempotency_key),
            ).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(
        self,
        *,
        workspace_id: str | None = None,
        status: JobStatus | None = None,
    ) -> list[JobRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def insert(self, record: JobRecord) -> JobRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, workspace_id, source_id, mode, idempotency_key,
                    status, created_at, updated_at, lease_expires_at, error, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.workspace_id,
                    record.source_id,
                    record.mode,
                    record.idempotency_key,
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.lease_expires_at,
                    record.error,
                    record.result_json,
                ),
            )
            conn.commit()
        loaded = self.get(record.job_id)
        assert loaded is not None
        return loaded

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        lease_expires_at: float | None = None,
        clear_lease: bool = False,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        clear_result: bool = False,
    ) -> JobRecord | None:
        current = self.get(job_id)
        if current is None:
            return None
        now = time.time()
        new_status = status or current.status
        new_lease = current.lease_expires_at
        if clear_lease:
            new_lease = None
        elif lease_expires_at is not None:
            new_lease = lease_expires_at
        result_json = current.result_json
        if clear_result:
            result_json = None
        elif result is not None:
            result_json = json.dumps(result)
        err = current.error if error is None else error
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs SET
                    status = ?,
                    updated_at = ?,
                    lease_expires_at = ?,
                    error = ?,
                    result_json = ?
                WHERE job_id = ?
                """,
                (new_status, now, new_lease, err, result_json, job_id),
            )
            conn.commit()
        return self.get(job_id)

    def active_lease(
        self,
        *,
        workspace_id: str,
        source_id: str,
        now: float | None = None,
    ) -> JobRecord | None:
        ts = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE workspace_id = ? AND source_id = ?
                  AND status IN ('queued', 'running')
                  AND (lease_expires_at IS NULL OR lease_expires_at > ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (workspace_id, source_id, ts),
            ).fetchone()
        return _row_to_job(row) if row else None

    def expire_stale_leases(self, *, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = COALESCE(error, 'lease expired'),
                    updated_at = ?,
                    lease_expires_at = NULL
                WHERE status IN ('queued', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (ts, ts),
            )
            conn.commit()
            return int(cur.rowcount or 0)


def _row_to_job(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=str(row["job_id"]),
        workspace_id=str(row["workspace_id"]),
        source_id=str(row["source_id"]),
        mode=str(row["mode"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        lease_expires_at=(
            float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None
        ),
        error=row["error"],
        result_json=row["result_json"],
    )
