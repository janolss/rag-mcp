"""Qdrant storage helpers with lock-aware connect retries."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Sequence

from qdrant_client import QdrantClient, models

from rag.config import Config

logger = logging.getLogger(__name__)

NAMESPACE = uuid.UUID("a4e2e5e0-6b8a-4f3d-9c1e-2d7f8a9b0c3e")


class QdrantLockError(RuntimeError):
    """Local Qdrant storage is locked by another process."""


def make_point_id(*parts: str) -> str:
    """Deterministic UUID5 from stable chunk identity parts."""
    return str(uuid.uuid5(NAMESPACE, "|".join(parts)))


def _is_lock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "already accessed" in message or "another process is using" in message


def lock_error_message(path: str) -> str:
    return (
        f"Qdrant local storage is locked: {path}. "
        "Only one process can use qdrant.mode=local at a time. "
        "Stop the other RAG process (Cursor MCP lk-rag and/or `rag.cli index`), "
        "wait a second, then retry — or switch to qdrant.mode=server "
        "(npm run rag:up) for concurrent MCP + indexing."
    )


class VectorStore:
    def __init__(
        self,
        config: Config,
        *,
        connect_retries: int | None = None,
        connect_retry_delay_ms: int | None = None,
    ):
        self._config = config
        self.collection = config.qdrant.collection
        retries = (
            connect_retries
            if connect_retries is not None
            else int(getattr(config.qdrant, "connect_retries", 10) or 10)
        )
        delay_ms = (
            connect_retry_delay_ms
            if connect_retry_delay_ms is not None
            else int(getattr(config.qdrant, "connect_retry_delay_ms", 500) or 500)
        )
        self.client = self._connect(retries=max(1, retries), delay_ms=max(0, delay_ms))

    def _connect(self, *, retries: int, delay_ms: int) -> QdrantClient:
        mode = self._config.qdrant.mode
        if mode == "memory":
            logger.info("Using in-memory Qdrant")
            return QdrantClient(location=":memory:")
        if mode == "server":
            logger.info("Connecting to Qdrant server at %s", self._config.qdrant.url)
            return QdrantClient(url=self._config.qdrant.url)
        if mode != "local":
            raise ValueError(f"Unsupported qdrant.mode: {mode}")

        path = str(self._config.qdrant_local_path)
        last_exc: BaseException | None = None
        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    "Using local Qdrant at %s (attempt %d/%d)",
                    path,
                    attempt,
                    retries,
                )
                return QdrantClient(path=path)
            except Exception as exc:  # noqa: BLE001 - qdrant raises RuntimeError / OSError variants
                last_exc = exc
                if not _is_lock_error(exc):
                    raise
                if attempt >= retries:
                    break
                logger.warning(
                    "Qdrant local lock busy (attempt %d/%d); retrying in %dms",
                    attempt,
                    retries,
                    delay_ms,
                )
                time.sleep(delay_ms / 1000.0)

        raise QdrantLockError(lock_error_message(path)) from last_exc

    def collection_exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def recreate_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info("Created collection '%s' (dim=%d)", self.collection, vector_size)
        # Payload indexes only apply to server Qdrant; local/memory modes ignore them.
        if self._config.qdrant.mode == "server":
            for field_name in ("type", "app", "file"):
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

    def upsert_chunks(
        self,
        chunks: Sequence[dict[str, Any]],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        if not chunks:
            return 0

        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = make_point_id(chunk["file"], str(chunk.get("chunk_index", 0)), chunk["content"])
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=list(vector),
                    payload={
                        "type": chunk["type"],
                        "app": chunk["app"],
                        "file": chunk["file"],
                        "language": chunk.get("language"),
                        "section": chunk.get("section"),
                        "chunk_index": chunk.get("chunk_index", 0),
                        "content": chunk["content"],
                    },
                )
            )

        batch_size = 64
        for start in range(0, len(points), batch_size):
            self.client.upsert(
                collection_name=self.collection,
                points=points[start : start + batch_size],
                wait=True,
            )
        return len(points)

    def count(self) -> int:
        if not self.collection_exists():
            return 0
        info = self.client.get_collection(self.collection)
        return int(info.points_count or 0)

    def search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        score_threshold: float | None,
        type_filter: list[str] | None = None,
        app_filter: str | None = None,
    ) -> list[models.ScoredPoint]:
        if not self.collection_exists():
            raise RuntimeError(
                f"Collection '{self.collection}' does not exist. Run: python -m rag.cli index"
            )

        must: list[models.FieldCondition] = []
        if type_filter:
            must.append(
                models.FieldCondition(
                    key="type",
                    match=models.MatchAny(any=type_filter),
                )
            )
        if app_filter:
            must.append(
                models.FieldCondition(
                    key="app",
                    match=models.MatchValue(value=app_filter),
                )
            )

        query_filter = models.Filter(must=must) if must else None
        results = self.client.query_points(
            collection_name=self.collection,
            query=list(query_vector),
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return list(results.points)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup on shutdown
            logger.debug("Error while closing Qdrant client", exc_info=True)


def build_type_app_filter(
    *,
    type_filter: list[str] | None = None,
    app_filter: str | None = None,
) -> models.Filter | None:
    """Pure helper used by tests and callers that need the filter object."""
    must: list[models.FieldCondition] = []
    if type_filter:
        must.append(
            models.FieldCondition(
                key="type",
                match=models.MatchAny(any=type_filter),
            )
        )
    if app_filter:
        must.append(
            models.FieldCondition(
                key="app",
                match=models.MatchValue(value=app_filter),
            )
        )
    return models.Filter(must=must) if must else None
