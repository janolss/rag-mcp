"""Concrete SearchService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.retrieval import search as retrieval
from rag.services.errors import ValidationError
from rag.services.resolve import resolve_workspace_id
from rag.store import VectorStore

_MAX_LIMIT = 50
_DEFAULT_LIMIT = 8


class SearchServiceImpl:
    def __init__(
        self,
        config: Config,
        *,
        store: VectorStore | None = None,
        embedder: EmbeddingClient | None = None,
    ):
        self.config = config
        self._store = store
        self._embedder = embedder

    def search(
        self,
        *,
        workspace_id: str | None = None,
        query: str,
        search_mode: str = "semantic",
        source_ids: list[str] | None = None,
        document_types: list[str] | None = None,
        limit: int | None = None,
        scope: str = "workspace",
        document_id: str | None = None,
        language: str | None = None,
        path_prefix: str | None = None,
        app_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        if not (query or "").strip():
            raise ValidationError("query cannot be empty")
        mode = (search_mode or "semantic").strip().lower()
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValidationError(
                f"unsupported search_mode {search_mode!r}; expected semantic|keyword|hybrid"
            )
        # Keyword/hybrid land in Phase 9; semantic is the only live mode for now.
        if mode != "semantic":
            raise ValidationError(
                f"search_mode {mode!r} is not enabled yet; use search_mode='semantic'"
            )

        resolved = resolve_workspace_id(self.config, workspace_id, required=True)
        assert resolved is not None
        top_k = _DEFAULT_LIMIT if limit is None else int(limit)
        if top_k < 1 or top_k > _MAX_LIMIT:
            raise ValidationError(f"limit must be between 1 and {_MAX_LIMIT}")

        type_filter = list(document_types) if document_types else ["documentation", "code", "test"]
        source_id = None
        if source_ids:
            if len(source_ids) != 1:
                raise ValidationError("exactly one source_id is supported per search call")
            source_id = source_ids[0]

        hits = retrieval.search_hits(
            self.config,
            query,
            type_filter=type_filter,
            app_filter=app_filter,
            path_prefix=path_prefix,
            workspace_id=resolved,
            source_id=source_id,
            document_id=document_id,
            language=language,
            scope=scope,
            top_k=top_k,
            store=self._store,
            embedder=self._embedder,
        )
        return [_hit_to_dict(hit) for hit in hits]


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    payload = hit.payload or {}
    return {
        "score": float(getattr(hit, "score", 0.0) or 0.0),
        "workspace_id": payload.get("workspace_id"),
        "source_id": payload.get("source_id"),
        "document_id": payload.get("document_id") or payload.get("file"),
        "file": payload.get("file"),
        "type": payload.get("type"),
        "app": payload.get("app"),
        "language": payload.get("language"),
        "section": payload.get("section"),
        "start_line": payload.get("start_line"),
        "end_line": payload.get("end_line"),
        "content": payload.get("content", ""),
        "requirement_ids": list(payload.get("requirement_ids") or []),
        "schema_version": payload.get("schema_version"),
        "revision": payload.get("revision"),
    }
