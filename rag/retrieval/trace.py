"""Trace requirements to documentation and code chunks."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.indexer.requirement_ids import (
    matches_requirement_id_pattern,
    normalize_requirement_query,
)
from rag.retrieval.search import format_hits, search_hits, validate_app
from rag.store import QdrantLockError, VectorStore


def trace_requirement(
    config: Config,
    requirement: str,
    *,
    app: str | None = None,
    top_k: int = 8,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    requirement = (requirement or "").strip()
    if not requirement:
        return "Error: requirement cannot be empty."

    try:
        app_filter = validate_app(config, app)
    except ValueError as exc:
        return f"Error: {exc}"

    patterns = config.index.requirement_id_patterns
    normalized = normalize_requirement_query(requirement, patterns)
    is_id = matches_requirement_id_pattern(normalized, patterns)

    owns_store = store is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)

        if is_id:
            doc_hits = _hits_for_id(
                config,
                store,
                embedder,
                normalized,
                type_filter=["documentation"],
                app_filter=None,
                top_k=top_k,
            )
            code_hits = _hits_for_id(
                config,
                store,
                embedder,
                normalized,
                type_filter=["code", "test"],
                app_filter=app_filter,
                top_k=top_k,
            )
        else:
            doc_hits = search_hits(
                config,
                normalized,
                type_filter=["documentation"],
                top_k=top_k,
                store=store,
                embedder=embedder,
            )
            code_hits = search_hits(
                config,
                normalized,
                type_filter=["code", "test"],
                app_filter=app_filter,
                top_k=top_k,
                store=store,
                embedder=embedder,
            )
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except RuntimeError as exc:
        return f"Error: {exc}"
    finally:
        if owns_store and store is not None:
            store.close()

    unmatched: list[str] = []
    if not doc_hits and not code_hits:
        unmatched.append(f"No indexed chunks matched {normalized!r}")
    elif not doc_hits:
        unmatched.append("No documentation chunks matched")
    elif not code_hits:
        unmatched.append("No code/test chunks matched")

    parts = [
        f"## Requirement\n{normalized}",
        "## Documentation\n" + (format_hits(doc_hits) if doc_hits else "_None_"),
        "## Code/Tests\n" + (format_hits(code_hits) if code_hits else "_None_"),
        "## Unmatched\n"
        + ("\n".join(f"- {u}" for u in unmatched) if unmatched else "- None"),
    ]
    return "\n\n".join(parts)


def _hits_for_id(
    config: Config,
    store: VectorStore,
    embedder: EmbeddingClient,
    requirement_id: str,
    *,
    type_filter: list[str],
    app_filter: str | None,
    top_k: int,
) -> list[Any]:
    # Prefer exact payload match via scroll; fall back to filtered vector search.
    records = store.scroll_by_requirement_id(
        requirement_id,
        limit=max(top_k * 2, 16),
        type_filter=type_filter,
        app_filter=app_filter,
    )
    if records:
        return [_RecordHit(r) for r in records[:top_k]]

    return search_hits(
        config,
        requirement_id,
        type_filter=type_filter,
        app_filter=app_filter,
        requirement_id=requirement_id,
        top_k=top_k,
        score_threshold=0.0,
        store=store,
        embedder=embedder,
    )


class _RecordHit:
    """Adapt scroll Records to the format_hits interface."""

    def __init__(self, record: Any):
        self.payload = record.payload or {}
        self.score = 1.0
        self.id = getattr(record, "id", None)
