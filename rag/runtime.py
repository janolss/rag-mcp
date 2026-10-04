"""Lazy shared runtime for the MCP server process."""

from __future__ import annotations

import atexit
import logging
import threading
from typing import TYPE_CHECKING

from rag.embeddings import EmbeddingClient
from rag.store import QdrantLockError, VectorStore

if TYPE_CHECKING:
    from rag.config import Config

logger = logging.getLogger(__name__)


class RagRuntime:
    """Thread-safe lazy holders so MCP can start even if Qdrant is briefly locked."""

    def __init__(self, config: Config):
        self.config = config
        self._embedder: EmbeddingClient | None = None
        self._store: VectorStore | None = None
        self._lock = threading.Lock()
        atexit.register(self.close)

    def get_embedder(self) -> EmbeddingClient:
        with self._lock:
            if self._embedder is None:
                self._embedder = EmbeddingClient(self.config.embedding)
            return self._embedder

    def get_store(self) -> VectorStore:
        with self._lock:
            if self._store is None:
                self._store = VectorStore(self.config)
            return self._store

    def try_warmup(self) -> str | None:
        """
        Attempt to open Qdrant at startup.

        Returns None on success, or an error string if the store is unavailable.
        MCP should still start so Cursor does not treat the server as crashed.
        """
        try:
            store = self.get_store()
            if not store.collection_exists():
                return (
                    f"Collection '{self.config.qdrant.collection}' is missing. "
                    "Run: python -m rag.cli index"
                )
            return None
        except QdrantLockError as exc:
            logger.warning("Qdrant unavailable at MCP startup: %s", exc)
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to warm up RAG store: %s", exc)
            return str(exc)

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None
