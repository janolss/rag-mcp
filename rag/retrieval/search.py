"""Vector retrieval with payload filters."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.store import QdrantLockError, VectorStore


def format_hits(hits: list[Any]) -> str:
    if not hits:
        return "No relevant results found."

    blocks: list[str] = []
    for hit in hits:
        payload = hit.payload or {}
        parts = [
            f"file: {payload.get('file', '?')}",
            f"type: {payload.get('type', '?')}",
            f"app: {payload.get('app', '?')}",
        ]
        section = payload.get("section")
        if section:
            parts.append(f"section: {section}")
        parts.append(f"score: {hit.score:.3f}")
        header = " | ".join(parts)
        content = payload.get("content", "")
        blocks.append(f"[{header}]\n{content}")
    return "\n\n---\n\n".join(blocks)


def search_knowledge(
    config: Config,
    query: str,
    *,
    top_k: int | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    return _search(
        config,
        query,
        type_filter=["documentation"],
        app_filter=None,
        top_k=top_k,
        store=store,
        embedder=embedder,
    )


def search_code(
    config: Config,
    query: str,
    *,
    app: str | None = None,
    top_k: int | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    app_filter = None
    if app:
        normalized = app.strip().lower()
        known = config.app_names
        if known and normalized not in known:
            return f"Error: app must be one of {sorted(known)} (got {app!r})"
        app_filter = normalized

    return _search(
        config,
        query,
        type_filter=["code", "test"],
        app_filter=app_filter,
        top_k=top_k,
        store=store,
        embedder=embedder,
    )


def _search(
    config: Config,
    query: str,
    *,
    type_filter: list[str],
    app_filter: str | None,
    top_k: int | None,
    store: VectorStore | None,
    embedder: EmbeddingClient | None,
) -> str:
    query = (query or "").strip()
    if not query:
        return "Error: Search query cannot be empty."

    owns_store = store is None
    owns_embedder = embedder is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)
        vector = embedder.embed_query(query)
        hits = store.search(
            vector,
            top_k=top_k or config.search.top_k,
            score_threshold=config.search.score_threshold,
            type_filter=type_filter,
            app_filter=app_filter,
        )
        return format_hits(hits)
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except RuntimeError as exc:
        return f"Error: {exc}"
    finally:
        if owns_store and store is not None:
            store.close()
