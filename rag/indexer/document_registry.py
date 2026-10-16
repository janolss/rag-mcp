"""SQLite document registry for incremental indexing state."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

DocumentStatus = Literal["active", "writing", "deleted"]

VALID_STATUSES: frozenset[str] = frozenset({"active", "writing", "deleted"})


@dataclass(frozen=True)
class DocumentRecord:
    workspace_id: str
    source_id: str
    document_id: str
    content_hash: str
    revision: int
    status: DocumentStatus
    observed_at: float
    path: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.workspace_id, self.source_id, self.document_id)


class DocumentRegistry:
    """Persistent registry of indexed documents (hash, revision, status)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    workspace_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (workspace_id, source_id, document_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_status
                ON documents(workspace_id, status)
                """
            )
            conn.commit()

    def get(
        self,
        workspace_id: str,
        source_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM documents
                WHERE workspace_id = ? AND source_id = ? AND document_id = ?
                """,
                (workspace_id, source_id, document_id),
            ).fetchone()
        return _row_to_record(row) if row else None

    def list_workspace(
        self,
        workspace_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[DocumentRecord]:
        with self._connect() as conn:
            if include_deleted:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE workspace_id = ? ORDER BY document_id",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM documents
                    WHERE workspace_id = ? AND status != 'deleted'
                    ORDER BY document_id
                    """,
                    (workspace_id,),
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    @overload
    def upsert(self, record: DocumentRecord) -> DocumentRecord: ...

    @overload
    def upsert(
        self,
        *,
        workspace_id: str,
        source_id: str,
        document_id: str,
        content_hash: str,
        revision: int,
        status: DocumentStatus,
        path: str = "",
        observed_at: float | None = None,
    ) -> DocumentRecord: ...

    def upsert(
        self,
        record: DocumentRecord | None = None,
        *,
        workspace_id: str | None = None,
        source_id: str | None = None,
        document_id: str | None = None,
        content_hash: str | None = None,
        revision: int | None = None,
        status: DocumentStatus | None = None,
        path: str = "",
        observed_at: float | None = None,
    ) -> DocumentRecord:
        if record is not None:
            workspace_id = record.workspace_id
            source_id = record.source_id
            document_id = record.document_id
            content_hash = record.content_hash
            revision = record.revision
            status = record.status
            path = record.path
            observed_at = record.observed_at

        if (
            not workspace_id
            or not source_id
            or not document_id
            or content_hash is None
            or revision is None
            or status is None
        ):
            raise TypeError(
                "upsert requires a DocumentRecord or workspace_id/source_id/"
                "document_id/content_hash/revision/status keyword arguments"
            )
        if status not in VALID_STATUSES:
            # Accept legacy "ready" as active.
            if status == "ready":  # type: ignore[comparison-overlap]
                status = "active"
            else:
                raise ValueError(f"invalid document status: {status!r}")

        ts = time.time() if observed_at is None else float(observed_at)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(
                    workspace_id, source_id, document_id, content_hash,
                    revision, status, observed_at, path
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, source_id, document_id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    revision=excluded.revision,
                    status=excluded.status,
                    observed_at=excluded.observed_at,
                    path=excluded.path
                """,
                (
                    workspace_id,
                    source_id,
                    document_id,
                    content_hash,
                    int(revision),
                    status,
                    ts,
                    path or document_id,
                ),
            )
            conn.commit()
        loaded = self.get(workspace_id, source_id, document_id)
        assert loaded is not None
        return loaded

    def mark_deleted(
        self,
        workspace_id: str,
        source_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        current = self.get(workspace_id, source_id, document_id)
        if current is None:
            return None
        return self.upsert(
            workspace_id=workspace_id,
            source_id=source_id,
            document_id=document_id,
            content_hash=current.content_hash,
            revision=current.revision,
            status="deleted",
            path=current.path,
        )

    def restore(self, record: DocumentRecord) -> DocumentRecord:
        return self.upsert(record)


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    status = str(row["status"])
    if status == "ready":
        status = "active"
    if status not in VALID_STATUSES:
        status = "active"
    return DocumentRecord(
        workspace_id=str(row["workspace_id"]),
        source_id=str(row["source_id"]),
        document_id=str(row["document_id"]),
        content_hash=str(row["content_hash"]),
        revision=int(row["revision"]),
        status=status,  # type: ignore[arg-type]
        observed_at=float(row["observed_at"]),
        path=str(row["path"] or ""),
    )
