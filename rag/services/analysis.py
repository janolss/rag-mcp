"""Context pack, requirement tracing, impact and gap analysis via retrieval."""

from __future__ import annotations

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.retrieval.context_pack import get_context_pack as _get_context_pack
from rag.retrieval.impact import find_gaps as _find_gaps
from rag.retrieval.impact import impact_of_change as _impact_of_change
from rag.retrieval.trace import trace_requirement as _trace_requirement
from rag.security.access import AccessDenied
from rag.services.errors import ServiceError
from rag.store import VectorStore


class AnalysisServiceImpl:
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

    def get_context_pack(
        self,
        *,
        task: str,
        app: str | None = None,
        top_k_docs: int = 5,
        top_k_code: int = 8,
        top_k_lis: int = 5,
        path_prefix: str | None = None,
    ) -> str:
        return self._run(
            _get_context_pack,
            task,
            app=app,
            top_k_docs=top_k_docs,
            top_k_code=top_k_code,
            top_k_lis=top_k_lis,
            path_prefix=path_prefix,
        )

    def trace_requirement(
        self,
        *,
        requirement: str,
        app: str | None = None,
        top_k: int = 8,
    ) -> str:
        return self._run(_trace_requirement, requirement, app=app, top_k=top_k)

    def impact_of_change(
        self,
        *,
        change: str,
        app: str | None = None,
        path_prefix: str | None = None,
        top_k: int = 8,
    ) -> str:
        return self._run(
            _impact_of_change,
            change,
            app=app,
            path_prefix=path_prefix,
            top_k=top_k,
        )

    def find_gaps(
        self,
        *,
        area: str,
        app: str | None = None,
        top_k: int = 10,
    ) -> str:
        return self._run(_find_gaps, area, app=app, top_k=top_k)

    def _run(self, fn, positional: str, **kwargs: object) -> str:
        try:
            return fn(
                self.config,
                positional,
                store=self._store,
                embedder=self._embedder,
                **kwargs,
            )
        except AccessDenied as exc:
            raise ServiceError(str(exc)) from exc
