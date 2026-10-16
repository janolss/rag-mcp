"""Vector retrieval with payload filters and lexical re-rank."""

from __future__ import annotations

import re
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.store import QdrantLockError, VectorStore
from rag.workspaces.registry import WorkspaceRegistry

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
        for lis_key in (
            "document_id",
            "doc_type",
            "process_area",
            "domain",
            "status",
            "title",
        ):
            value = payload.get(lis_key)
            if value:
                parts.append(f"{lis_key}: {value}")
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
        except Exception:
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
    doc_type: str | None = None,
    process_area: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    workspace_id: str | None = None,
    source_id: str | None = None,
    document_id: str | None = None,
    language: str | None = None,
    scope: str = "workspace",
    allow_legacy: bool | None = None,
    related_workspace_ids: list[str] | None = None,
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
    threshold = config.search.score_threshold if score_threshold is None else score_threshold

    # Legacy MCP tools default to the synthetic default workspace. Multi-workspace
    # configs must pass an explicit workspace_id (allow_legacy=False).
    resolved_workspace = workspace_id
    registry = WorkspaceRegistry.from_config(config)
    if resolved_workspace is None:
        if len(registry) == 1 and registry.ids()[0] == "default":
            resolved_workspace = "default"
            legacy = True if allow_legacy is None else allow_legacy
        else:
            if allow_legacy:
                legacy = True
            else:
                raise ValueError(
                    "workspace_id is required when more than one workspace is registered"
                )
    else:
        legacy = bool(allow_legacy) if allow_legacy is not None else False

    expanded_related = related_workspace_ids
    if (scope or "workspace").strip().lower() == "related" and expanded_related is None:
        from rag.relationships.registry import RelationshipRegistry
        from rag.security.http_auth import require_principal

        principal = require_principal()
        assert resolved_workspace is not None
        rel_registry = RelationshipRegistry.from_workspace_registry(registry)
        expanded_related = rel_registry.related_workspace_ids(
            resolved_workspace,
            principal=principal,
            include_self=True,
            max_depth=1,
        )

    owns_store = store is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)
        vector = embedder.embed_query(query)
        hits = store.search(
            vector,
            top_k=fetch_k,
            score_threshold=threshold,
            workspace_id=resolved_workspace,
            allow_legacy=legacy,
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
            related_workspace_ids=expanded_related,
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


def search_lis(
    config: Config,
    query: str,
    *,
    top_k: int | None = None,
    path_prefix: str | None = None,
    doc_type: str | None = None,
    process_area: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    return _search(
        config,
        query,
        type_filter=["lis"],
        app_filter=None,
        path_prefix=path_prefix,
        doc_type=_optional_str(doc_type),
        process_area=_optional_str(process_area),
        domain=_optional_str(domain),
        status=_optional_str(status),
        top_k=top_k,
        store=store,
        embedder=embedder,
    )


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


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
    doc_type: str | None = None,
    process_area: str | None = None,
    domain: str | None = None,
    status: str | None = None,
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
            doc_type=doc_type,
            process_area=process_area,
            domain=domain,
            status=status,
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
