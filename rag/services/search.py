"""Concrete SearchService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.retrieval import search as retrieval
from rag.retrieval.fusion import reciprocal_rank_fusion
from rag.retrieval.lexical import LexicalHit, LexicalIndex, lexical_index_path
from rag.security.access import AccessDenied, authorize_source, authorize_workspace
from rag.security.http_auth import require_principal
from rag.services.errors import ForbiddenError, ServiceError, ValidationError
from rag.services.resolve import resolve_workspace_id
from rag.store import QdrantLockError, VectorStore

_MAX_LIMIT = 50
_DEFAULT_LIMIT = 8


class _ScoredHit:
    def __init__(self, point_id: str, score: float, payload: dict[str, Any]):
        self.id = point_id
        self.point_id = point_id
        self.score = score
        self.payload = payload


class SearchServiceImpl:
    def __init__(
        self,
        config: Config,
        *,
        store: VectorStore | None = None,
        embedder: EmbeddingClient | None = None,
        lexical: LexicalIndex | None = None,
    ):
        self.config = config
        self._store = store
        self._embedder = embedder
        self._lexical = lexical

    def _lexical_index(self) -> LexicalIndex:
        if self._lexical is not None:
            return self._lexical
        return LexicalIndex(lexical_index_path(self.config.status_file_path))

    def search(
        self,
        *,
        workspace_id: str | None = None,
        query: str,
        search_mode: str | None = None,
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
        mode = (search_mode or self.config.search.default_mode or "semantic").strip().lower()
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValidationError(
                f"unsupported search_mode {search_mode!r}; expected semantic|keyword|hybrid"
            )

        resolved = resolve_workspace_id(self.config, workspace_id, required=True)
        assert resolved is not None
        principal = require_principal()
        try:
            authorize_workspace(principal, resolved)
        except AccessDenied as exc:
            raise ForbiddenError(str(exc)) from exc

        top_k = _DEFAULT_LIMIT if limit is None else int(limit)
        if top_k < 1 or top_k > _MAX_LIMIT:
            raise ValidationError(f"limit must be between 1 and {_MAX_LIMIT}")

        type_filter = list(document_types) if document_types else ["documentation", "code", "test"]
        source_id = None
        if source_ids:
            if len(source_ids) != 1:
                raise ValidationError("exactly one source_id is supported per search call")
            source_id = source_ids[0]
            try:
                authorize_source(principal, source_id)
            except AccessDenied as exc:
                raise ForbiddenError(str(exc)) from exc

        if mode == "keyword":
            return self._keyword_search(
                query=query,
                workspace_id=resolved,
                source_id=source_id,
                limit=top_k,
            )
        if mode == "hybrid":
            return self._hybrid_search(
                query=query,
                workspace_id=resolved,
                source_id=source_id,
                type_filter=type_filter,
                document_id=document_id,
                language=language,
                scope=scope,
                path_prefix=path_prefix,
                app_filter=app_filter,
                limit=top_k,
            )

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

    def search_knowledge(
        self,
        *,
        query: str,
        top_k: int | None = None,
        path_prefix: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        return self._text_search(
            retrieval.search_knowledge,
            query,
            top_k=top_k,
            path_prefix=path_prefix,
            workspace_id=workspace_id,
        )

    def search_code(
        self,
        *,
        query: str,
        app: str | None = None,
        top_k: int | None = None,
        path_prefix: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        return self._text_search(
            retrieval.search_code,
            query,
            app=app,
            top_k=top_k,
            path_prefix=path_prefix,
            workspace_id=workspace_id,
        )

    def search_lis(
        self,
        *,
        query: str,
        top_k: int | None = None,
        path_prefix: str | None = None,
        workspace_id: str | None = None,
        doc_type: str | None = None,
        process_area: str | None = None,
        domain: str | None = None,
        status: str | None = None,
    ) -> str:
        return self._text_search(
            retrieval.search_lis,
            query,
            top_k=top_k,
            path_prefix=path_prefix,
            workspace_id=workspace_id,
            doc_type=doc_type,
            process_area=process_area,
            domain=domain,
            status=status,
        )

    def _text_search(self, fn, query: str, **kwargs: Any) -> str:
        try:
            return fn(
                self.config,
                query,
                store=self._store,
                embedder=self._embedder,
                **kwargs,
            )
        except AccessDenied as exc:
            raise ForbiddenError(str(exc)) from exc
        except QdrantLockError as exc:
            raise ServiceError(str(exc)) from exc

    def _keyword_search(
        self,
        *,
        query: str,
        workspace_id: str,
        source_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        hits = self._lexical_index().search(
            query,
            workspace_id=workspace_id,
            source_id=source_id,
            limit=limit,
        )
        return [_lexical_to_dict(hit) for hit in hits]

    def _hybrid_search(
        self,
        *,
        query: str,
        workspace_id: str,
        source_id: str | None,
        type_filter: list[str],
        document_id: str | None,
        language: str | None,
        scope: str,
        path_prefix: str | None,
        app_filter: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        fetch_k = max(limit * 3, limit)
        semantic_hits = retrieval.search_hits(
            self.config,
            query,
            type_filter=type_filter,
            app_filter=app_filter,
            path_prefix=path_prefix,
            workspace_id=workspace_id,
            source_id=source_id,
            document_id=document_id,
            language=language,
            scope=scope,
            top_k=fetch_k,
            store=self._store,
            embedder=self._embedder,
        )
        semantic_ranked = [
            _ScoredHit(
                point_id=str((h.payload or {}).get("point_id") or id(h)),
                score=float(getattr(h, "score", 0.0) or 0.0),
                payload=dict(h.payload or {}),
            )
            for h in semantic_hits
        ]
        lexical_hits = self._lexical_index().search(
            query,
            workspace_id=workspace_id,
            source_id=source_id,
            limit=fetch_k,
        )
        lexical_ranked = [
            _ScoredHit(point_id=h.point_id, score=h.score, payload=h.payload) for h in lexical_hits
        ]
        fused = reciprocal_rank_fusion(
            [semantic_ranked, lexical_ranked],
            id_fn=lambda item: item.point_id,
            k=int(self.config.search.rrf_k),
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for point_id, score, item in fused:
            payload = dict(item.payload)
            payload["point_id"] = point_id
            results.append(
                {
                    "score": float(score),
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
                    "search_mode": "hybrid",
                }
            )
        return results


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
        "search_mode": "semantic",
    }


def _lexical_to_dict(hit: LexicalHit) -> dict[str, Any]:
    payload = hit.payload
    return {
        "score": float(hit.score),
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
        "search_mode": "keyword",
        "point_id": hit.point_id,
    }
