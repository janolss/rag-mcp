"""Collection routing for atomic blue/green index swaps."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.store import VectorStore


@dataclass
class GenerationInfo:
    name: str
    vector_size: int
    created_at: float


class CollectionRouter:
    """
    Resolve the active Qdrant collection generation.

    Server mode can use Qdrant aliases when available. Local/memory modes store
    the active generation pointer in SQLite so a failed rebuild never replaces
    the live collection until activate() succeeds.
    """

    def __init__(self, config: Config, *, state_path: Path | None = None):
        self.config = config
        self.base_name = config.qdrant.collection
        self.state_path = state_path or (
            config.status_file_path.parent / "collection_router.sqlite3"
        )
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.state_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS active_generation (
                    base_name TEXT PRIMARY KEY,
                    generation TEXT NOT NULL,
                    vector_size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    previous TEXT
                )
                """
            )
            conn.commit()

    def active_collection(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation FROM active_generation WHERE base_name = ?",
                (self.base_name,),
            ).fetchone()
        return str(row["generation"]) if row else self.base_name

    def previous_collection(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT previous FROM active_generation WHERE base_name = ?",
                (self.base_name,),
            ).fetchone()
        if not row or not row["previous"]:
            return None
        return str(row["previous"])

    def staging_collection(self) -> str:
        return f"{self.base_name}__staging_{int(time.time())}"

    def activate(self, generation: str, *, vector_size: int) -> None:
        previous = self.active_collection()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO active_generation(base_name, generation, vector_size, created_at, previous)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(base_name) DO UPDATE SET
                    generation=excluded.generation,
                    vector_size=excluded.vector_size,
                    created_at=excluded.created_at,
                    previous=excluded.previous
                """,
                (self.base_name, generation, vector_size, time.time(), previous),
            )
            conn.commit()
        if self.config.qdrant.mode == "server":
            self._update_alias(generation)

    def rollback(self) -> str | None:
        previous = self.previous_collection()
        if not previous:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT vector_size FROM active_generation WHERE base_name = ?",
                (self.base_name,),
            ).fetchone()
            vector_size = int(row["vector_size"]) if row else 0
        self.activate(previous, vector_size=vector_size)
        return previous

    def _update_alias(self, generation: str) -> None:
        store = VectorStore(self.config)
        try:
            client = store.client
            # Best-effort alias update; older clients may lack alias APIs.
            if hasattr(client, "update_collection_aliases"):
                from qdrant_client import models

                client.update_collection_aliases(
                    change_aliases_operations=[
                        models.DeleteAliasOperation(
                            delete_alias=models.DeleteAlias(alias_name=self.base_name)
                        ),
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(
                                collection_name=generation,
                                alias_name=self.base_name,
                            )
                        ),
                    ]
                )
        finally:
            store.close()

    def export_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM active_generation WHERE base_name = ?",
                (self.base_name,),
            ).fetchone()
        if not row:
            return {"base_name": self.base_name, "generation": self.base_name}
        return dict(row)
