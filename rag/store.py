"""Qdrant storage helpers with lock-aware connect retries."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from qdrant_client import QdrantClient, models

from rag.config import Config

logger = logging.getLogger(__name__)

NAMESPACE = uuid.UUID("a4e2e5e0-6b8a-4f3d-9c1e-2d7f8a9b0c3e")

SearchScope = Literal["workspace", "source", "related", "global"]
VALID_SCOPES: frozenset[str] = frozenset({"workspace", "source", "related", "global"})
# global stays disabled until an explicit cross-tenant policy exists.
DISABLED_SCOPES: frozenset[str] = frozenset({"global"})


class QdrantLockError(RuntimeError):
    """Local Qdrant storage is locked by another process."""


class WorkspaceFilterError(ValueError):
    """Raised when a storage operation lacks a required workspace_id."""


class ScopeDisabledError(ValueError):
    """Raised when a search scope is not yet enabled."""


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
        "Checklist: (1) stop the other RAG process (Cursor MCP and/or "
        "`python -m rag.cli index`), (2) wait a second and retry, "
        "(3) run `python -m rag.cli doctor`, or (4) switch to "
        "qdrant.mode=server and `npm run rag:up` for concurrent MCP + indexing."
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
            api_key = (self._config.qdrant.api_key or "").strip() or None
            return QdrantClient(url=self._config.qdrant.url, api_key=api_key)
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
            except Exception as exc:
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

    def ensure_collection(self, vector_size: int) -> None:
        """Create collection if missing; leave existing data intact."""
        if self.collection_exists():
            return
        self._create_collection(vector_size)

    def recreate_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self._create_collection(vector_size)

    def _create_collection(self, vector_size: int) -> None:
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
            for field_name in (
                "type",
                "app",
                "file",
                "requirement_ids",
                "document_id",
                "doc_type",
                "process_area",
                "domain",
                "status",
            ):
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            for field_name in ("workspace_id", "source_id", "language"):
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
        for chunk, vector in zip(chunks, vectors, strict=True):
            workspace_id = chunk.get("workspace_id")
            source_id = chunk.get("source_id")
            if workspace_id and source_id:
                from rag.indexer.payload import build_payload

                payload = build_payload(
                    chunk,
                    workspace_id=str(workspace_id),
                    source_id=str(source_id),
                    revision=int(chunk.get("revision") or 1),
                )
                point_id = payload.pop("point_id")
            else:
                # Legacy single-workspace payload (content included in ID).
                point_id = make_point_id(
                    chunk["file"], str(chunk.get("chunk_index", 0)), chunk["content"]
                )
                payload = {
                    "type": chunk["type"],
                    "app": chunk["app"],
                    "file": chunk["file"],
                    "language": chunk.get("language"),
                    "section": chunk.get("section"),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "content": chunk["content"],
                    "requirement_ids": list(chunk.get("requirement_ids") or []),
                    "schema_version": 0,
                }
                for lis_key in (
                    "document_id",
                    "doc_type",
                    "process_area",
                    "domain",
                    "status",
                    "title",
                ):
                    value = chunk.get(lis_key)
                    if value:
                        payload[lis_key] = value
                if chunk.get("start_line") is not None:
                    payload["start_line"] = chunk["start_line"]
                if chunk.get("end_line") is not None:
                    payload["end_line"] = chunk["end_line"]
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=list(vector),
                    payload=payload,
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

    def delete_by_files(
        self,
        files: Sequence[str],
        *,
        workspace_id: str,
    ) -> None:
        """Delete all points whose payload.file is in files (workspace-scoped)."""
        if not files or not self.collection_exists():
            return
        if not (workspace_id or "").strip():
            raise WorkspaceFilterError("workspace_id is required for delete_by_files")
        unique = sorted({f.replace("\\", "/") for f in files if f})
        if not unique:
            return
        must = [
            models.FieldCondition(
                key="file",
                match=models.MatchAny(any=unique),
            ),
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=workspace_id),
            ),
        ]
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=must)),
            wait=True,
        )

    def delete_by_document(
        self,
        *,
        workspace_id: str,
        source_id: str,
        document_id: str,
    ) -> None:
        """Delete all points for one logical document."""
        if not self.collection_exists():
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=workspace_id),
                        ),
                        models.FieldCondition(
                            key="source_id",
                            match=models.MatchValue(value=source_id),
                        ),
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                    ]
                )
            ),
            wait=True,
        )

    def delete_by_workspace(self, workspace_id: str) -> None:
        """Delete every point belonging to ``workspace_id`` in the active collection."""
        if not workspace_id or not self.collection_exists():
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=workspace_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def scroll_document_points(
        self,
        *,
        workspace_id: str,
        source_id: str,
        document_id: str,
        revision: int | None = None,
        limit: int = 256,
    ) -> list[models.Record]:
        if not self.collection_exists():
            return []
        must: list[models.Condition] = [
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=workspace_id),
            ),
            models.FieldCondition(
                key="source_id",
                match=models.MatchValue(value=source_id),
            ),
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            ),
        ]
        if revision is not None:
            must.append(
                models.FieldCondition(
                    key="revision",
                    match=models.MatchValue(value=int(revision)),
                )
            )
        records, _offset = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=models.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(records)

    def delete_document_points_except(
        self,
        *,
        workspace_id: str,
        source_id: str,
        document_id: str,
        keep_point_ids: set[str] | Sequence[str],
    ) -> None:
        """Retire document points whose IDs are not in keep_point_ids."""
        if not self.collection_exists():
            return
        keep = {str(pid) for pid in keep_point_ids}
        existing = self.scroll_document_points(
            workspace_id=workspace_id,
            source_id=source_id,
            document_id=document_id,
        )
        retire_ids = [str(point.id) for point in existing if str(point.id) not in keep]
        if not retire_ids:
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=retire_ids),
            wait=True,
        )

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
        workspace_id: str | None = None,
        scope: SearchScope | str = "workspace",
        source_id: str | None = None,
        document_id: str | None = None,
        language: str | None = None,
        type_filter: list[str] | None = None,
        app_filter: str | None = None,
        requirement_id: str | None = None,
        doc_type: str | None = None,
        process_area: str | None = None,
        domain: str | None = None,
        status: str | None = None,
        related_workspace_ids: list[str] | None = None,
    ) -> list[models.ScoredPoint]:
        if not self.collection_exists():
            raise RuntimeError(
                f"Collection '{self.collection}' does not exist. Run: python -m rag.cli index"
            )

        query_filter = build_type_app_filter(
            workspace_id=workspace_id,
            scope=scope,
            source_id=source_id,
            document_id=document_id,
            language=language,
            type_filter=type_filter,
            app_filter=app_filter,
            requirement_id=requirement_id,
            doc_type=doc_type,
            process_area=process_area,
            domain=domain,
            status=status,
            related_workspace_ids=related_workspace_ids,
        )
        results = self.client.query_points(
            collection_name=self.collection,
            query=list(query_vector),
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return list(results.points)

    def scroll_by_requirement_id(
        self,
        requirement_id: str,
        *,
        limit: int = 32,
        workspace_id: str | None = None,
        type_filter: list[str] | None = None,
        app_filter: str | None = None,
    ) -> list[models.Record]:
        if not self.collection_exists():
            raise RuntimeError(
                f"Collection '{self.collection}' does not exist. Run: python -m rag.cli index"
            )
        query_filter = build_type_app_filter(
            workspace_id=workspace_id,
            type_filter=type_filter,
            app_filter=app_filter,
            requirement_id=requirement_id,
        )
        records, _offset = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(records)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            logger.debug("Error while closing Qdrant client", exc_info=True)


def _workspace_condition(*, workspace_id: str | None) -> models.FieldCondition:
    if workspace_id:
        return models.FieldCondition(
            key="workspace_id",
            match=models.MatchValue(value=workspace_id),
        )
    raise WorkspaceFilterError("workspace_id is required for storage filters")


def resolve_search_scope(scope: SearchScope | str | None) -> str:
    """Validate scope; ``global`` stays disabled."""
    normalized = (scope or "workspace").strip().lower()
    if normalized not in VALID_SCOPES:
        raise ValueError(
            f"unsupported search scope: {scope!r}; expected one of {sorted(VALID_SCOPES)}"
        )
    if normalized in DISABLED_SCOPES:
        raise ScopeDisabledError(
            f"search scope {normalized!r} is disabled; use scope='workspace', "
            "'source', or 'related'"
        )
    return normalized


def build_type_app_filter(
    *,
    workspace_id: str | None = None,
    scope: SearchScope | str = "workspace",
    source_id: str | None = None,
    document_id: str | None = None,
    language: str | None = None,
    type_filter: list[str] | None = None,
    app_filter: str | None = None,
    requirement_id: str | None = None,
    doc_type: str | None = None,
    process_area: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    related_workspace_ids: list[str] | None = None,
) -> models.Filter | None:
    """
    Build a Qdrant payload filter.

    ``workspace_id`` is required for workspace/source scopes. Scope ``global``
    raises ``ScopeDisabledError``. Scope ``related`` requires
    ``related_workspace_ids`` (authorized expansion).
    """
    resolved_scope = resolve_search_scope(scope)
    must: list[models.FieldCondition] = []

    if resolved_scope == "related":
        if related_workspace_ids is None:
            raise ValueError(
                "scope='related' requires related_workspace_ids "
                "(authorized expansion from the starting workspace)"
            )
        ids = list(related_workspace_ids)
        if workspace_id and workspace_id not in ids:
            ids = [workspace_id, *ids]
        if not ids:
            raise ValueError("scope='related' related_workspace_ids cannot be empty")
        must.append(
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchAny(any=ids),
            )
        )
    else:
        must.append(_workspace_condition(workspace_id=workspace_id))

    if resolved_scope == "source":
        if not source_id:
            raise ValueError("scope='source' requires source_id")
        must.append(
            models.FieldCondition(
                key="source_id",
                match=models.MatchValue(value=source_id),
            )
        )
    elif source_id:
        must.append(
            models.FieldCondition(
                key="source_id",
                match=models.MatchValue(value=source_id),
            )
        )

    if document_id:
        must.append(
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            )
        )
    if language:
        must.append(
            models.FieldCondition(
                key="language",
                match=models.MatchValue(value=language),
            )
        )
    if type_filter:
        must.append(
            models.FieldCondition(
                key="type",
                match=models.MatchAny(any=type_filter),
            )
        )
    if app_filter:
        # Deprecated compatibility filter (prefer source_id / path metadata).
        must.append(
            models.FieldCondition(
                key="app",
                match=models.MatchValue(value=app_filter),
            )
        )
    if requirement_id:
        must.append(
            models.FieldCondition(
                key="requirement_ids",
                match=models.MatchValue(value=requirement_id),
            )
        )
    for key, value in (
        ("doc_type", doc_type),
        ("process_area", process_area),
        ("domain", domain),
        ("status", status),
    ):
        if value:
            must.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )
    return models.Filter(must=must) if must else None
