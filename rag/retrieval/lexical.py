"""SQLite FTS5 keyword index independent of vector retrieval."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9_./-]+", re.IGNORECASE)


@dataclass(frozen=True)
class LexicalHit:
    point_id: str
    score: float
    payload: dict[str, Any]


class LexicalIndex:
    """Persistent FTS5 index keyed by point_id with workspace isolation."""

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
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(
                    point_id UNINDEXED,
                    workspace_id UNINDEXED,
                    source_id UNINDEXED,
                    document_id UNINDEXED,
                    file UNINDEXED,
                    body,
                    tokenize = 'porter unicode61'
                )
                """
            )
            conn.commit()

    def upsert_documents(self, documents: list[dict[str, Any]]) -> int:
        if not documents:
            return 0
        with self._connect() as conn:
            for doc in documents:
                point_id = str(doc["point_id"])
                conn.execute("DELETE FROM chunks_fts WHERE point_id = ?", (point_id,))
                conn.execute(
                    """
                    INSERT INTO chunks_fts(
                        point_id, workspace_id, source_id, document_id, file, body
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        point_id,
                        str(doc.get("workspace_id") or ""),
                        str(doc.get("source_id") or ""),
                        str(doc.get("document_id") or doc.get("file") or ""),
                        str(doc.get("file") or ""),
                        str(doc.get("content") or ""),
                    ),
                )
            conn.commit()
        return len(documents)

    def delete_point_ids(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM chunks_fts WHERE point_id = ?",
                [(pid,) for pid in point_ids],
            )
            conn.commit()

    def search(
        self,
        query: str,
        *,
        workspace_id: str,
        limit: int = 20,
        source_id: str | None = None,
    ) -> list[LexicalHit]:
        tokens = [t for t in _TOKEN_RE.findall(query or "") if len(t) > 1]
        if not tokens:
            return []
        # Escape FTS5 special chars by quoting each token.
        match = " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)
        clauses = ["workspace_id = ?", "chunks_fts MATCH ?"]
        params: list[Any] = [workspace_id, match]
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        params.append(int(limit))
        sql = f"""
            SELECT point_id, workspace_id, source_id, document_id, file, body,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts
            WHERE {" AND ".join(clauses)}
            ORDER BY rank
            LIMIT ?
        """
        with self._connect() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        hits: list[LexicalHit] = []
        for row in rows:
            # bm25 returns negative ranks (lower is better); invert for score.
            rank = float(row["rank"])
            score = 1.0 / (1.0 + abs(rank))
            hits.append(
                LexicalHit(
                    point_id=str(row["point_id"]),
                    score=score,
                    payload={
                        "point_id": row["point_id"],
                        "workspace_id": row["workspace_id"],
                        "source_id": row["source_id"],
                        "document_id": row["document_id"],
                        "file": row["file"],
                        "content": row["body"],
                    },
                )
            )
        return hits


def lexical_index_path(status_file: Path) -> Path:
    return status_file.parent / "lexical.sqlite3"
