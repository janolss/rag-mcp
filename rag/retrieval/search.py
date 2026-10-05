"""Vector retrieval with payload filters and lexical re-rank."""

from __future__ import annotations

import re
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.store import QdrantLockError, VectorStore

_TOKEN_RE = re.compile(r"[a-z0-9_./-]+", re.IGNORECASE)


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
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            parts.append(f"lines: {start_line}-{end_line}")
        req_ids = payload.get("requirement_ids") or []
        if req_ids:
            parts.append(f"requirement_ids: {','.join(req_ids)}")
        score = getattr(hit, "score", None)
        if score is not None:
            parts.append(f"score: {float(score):.3f}")
        header = " | ".join(parts)
        content = payload.get("content", "")
        blocks.append(f"[{header}]\n{content}")
    return "\n\n---\n\n".join(blocks)


def lexical_score(query: str, payload: dict[str, Any] | None) -> float:
    tokens = {t.lower() for t in _TOKEN_RE.findall(query or "") if len(t) > 1}
    if not tokens:
        return 0.0
    payload = payload or {}
    text = f"{payload.get('content', '')} {payload.get('file', '')}".lower()
    hits = sum(1 for t in tokens if t in text)
    return hits / len(tokens)


def apply_path_prefix(hits: list[Any], path_prefix: str | None) -> list[Any]:
    if not path_prefix:
        return hits
    prefix = path_prefix.replace("\\", "/").lstrip("./")
    if not prefix:
        return hits
    return [
        h
        for h in hits
        if str((h.payload or {}).get("file", "")).replace("\\", "/").startswith(prefix)
    ]


def rerank_hits(
    hits: list[Any],
    query: str,
    *,
    vector_weight: float,
    lexical_weight: float,
    top_k: int,
) -> list[Any]:
    if not hits:
        return []
    vw = max(0.0, float(vector_weight))
    lw = max(0.0, float(lexical_weight))
    total = vw + lw
    if total <= 0:
        vw, lw, total = 1.0, 0.0, 1.0
    vw, lw = vw / total, lw / total

    scored: list[tuple[float, Any]] = []
    for hit in hits:
        vector = float(getattr(hit, "score", 0.0) or 0.0)
        lex = lexical_score(query, hit.payload)
        final = vw * vector + lw * lex
        # Preserve original score attribute for display as final blended score
        try:
            hit.score = final
        except Exception:  # noqa: BLE001 - ScoredPoint may be frozen in some versions
            pass
        scored.append((final, hit))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [h for _, h in scored[:top_k]]


def search_hits(
    config: Config,
    query: str,
    *,
    type_filter: list[str],
    app_filter: str | None = None,
    path_prefix: str | None = None,
    requirement_id: str | None = None,
    top_k: int | None = None,
    score_threshold: float | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> list[Any]:
    query = (query or "").strip()
    if not query:
        return []

    limit = top_k or config.search.top_k
    # Over-fetch when path filter or lexical re-rank may drop/reorder candidates
    fetch_k = limit * 3 if (path_prefix or config.search.lexical_weight > 0) else limit
    threshold = (
        config.search.score_threshold if score_threshold is None else score_threshold
    )

    owns_store = store is None
    owns_embedder = embedder is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)
        vector = embedder.embed_query(query)
        hits = store.search(
            vector,
            top_k=fetch_k,
            score_threshold=threshold,
            type_filter=type_filter,
            app_filter=app_filter,
            requirement_id=requirement_id,
        )
        hits = apply_path_prefix(hits, path_prefix)
        return rerank_hits(
            hits,
            query,
            vector_weight=config.search.vector_weight,
            lexical_weight=config.search.lexical_weight,
            top_k=limit,
        )
    finally:
        if owns_store and store is not None:
            store.close()


def search_knowledge(
    config: Config,
    query: str,
    *,
    top_k: int | None = None,
    path_prefix: str | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    return _search(
        config,
        query,
        type_filter=["documentation"],
        app_filter=None,
        path_prefix=path_prefix,
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
    path_prefix: str | None = None,
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
        path_prefix=path_prefix,
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
    path_prefix: str | None,
    top_k: int | None,
    store: VectorStore | None,
    embedder: EmbeddingClient | None,
) -> str:
    query = (query or "").strip()
    if not query:
        return "Error: Search query cannot be empty."

    try:
        hits = search_hits(
            config,
            query,
            type_filter=type_filter,
            app_filter=app_filter,
            path_prefix=path_prefix,
            top_k=top_k,
            store=store,
            embedder=embedder,
        )
        return format_hits(hits)
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except RuntimeError as exc:
        return f"Error: {exc}"


def validate_app(config: Config, app: str | None) -> str | None:
    """Return normalized app filter or raise ValueError / return error string pattern."""
    if not app:
        return None
    normalized = app.strip().lower()
    known = config.app_names
    if known and normalized not in known:
        raise ValueError(f"app must be one of {sorted(known)} (got {app!r})")
    return normalized
