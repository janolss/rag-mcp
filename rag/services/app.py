"""Facade bundling concrete service implementations for adapters."""

from __future__ import annotations

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.services.analysis import AnalysisServiceImpl
from rag.services.documents import DocumentServiceImpl
from rag.services.search import SearchServiceImpl
from rag.services.sources import SourceServiceImpl
from rag.services.status import StatusServiceImpl
from rag.services.workspaces import WorkspaceServiceImpl
from rag.store import VectorStore


class ServiceApp:
    """Application services shared by MCP and HTTP adapters."""

    def __init__(
        self,
        config: Config,
        *,
        store: VectorStore | None = None,
        embedder: EmbeddingClient | None = None,
    ):
        self.config = config
        self.workspaces = WorkspaceServiceImpl(config)
        self.sources = SourceServiceImpl(config)
        self.search = SearchServiceImpl(config, store=store, embedder=embedder)
        self.documents = DocumentServiceImpl(config)
        self.status = StatusServiceImpl(config)
        self.analysis = AnalysisServiceImpl(config, store=store, embedder=embedder)

    def with_runtime(
        self,
        *,
        store: VectorStore | None = None,
        embedder: EmbeddingClient | None = None,
    ) -> ServiceApp:
        return ServiceApp(self.config, store=store, embedder=embedder)
