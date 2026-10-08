"""Assemble a structured context pack from knowledge + code search."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.retrieval.search import format_hits, search_hits, validate_app
from rag.store import QdrantLockError, VectorStore


def get_context_pack(
    config: Config,
    task: str,
    *,
    app: str | None = None,
    top_k_docs: int = 5,
    top_k_code: int = 8,
    top_k_lis: int = 5,
    path_prefix: str | None = None,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    task = (task or "").strip()
    if not task:
        return "Error: task cannot be empty."

    try:
        app_filter = validate_app(config, app)
    except ValueError as exc:
        return f"Error: {exc}"

    caps = config.mcp.capabilities
    owns_store = store is None
    doc_hits: list[Any] = []
    code_hits: list[Any] = []
    lis_hits: list[Any] = []
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)

        if caps.knowledge:
            doc_hits = search_hits(
                config,
                task,
                type_filter=["documentation"],
                path_prefix=path_prefix,
                top_k=top_k_docs,
                store=store,
                embedder=embedder,
            )
        if caps.code:
            code_hits = search_hits(
                config,
                task,
                type_filter=["code", "test"],
                app_filter=app_filter,
                path_prefix=path_prefix,
                top_k=top_k_code,
                store=store,
                embedder=embedder,
            )
        if caps.lis:
            lis_hits = search_hits(
                config,
                task,
                type_filter=["lis"],
                path_prefix=path_prefix,
                top_k=top_k_lis,
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

    files = _ranked_files(doc_hits + code_hits + lis_hits)
    gaps: list[str] = []
    if caps.knowledge and not doc_hits:
        gaps.append("No documentation hits above threshold")
    if caps.code and not code_hits:
        gaps.append("No code hits above threshold")
    if caps.lis and not lis_hits:
        gaps.append("No LIS hits above threshold")

    sections = [f"## Task\n{task}"]
    if caps.knowledge:
        sections.append(
            "## Documentation\n" + (format_hits(doc_hits) if doc_hits else "_None_")
        )
    if caps.lis:
        sections.append("## LIS\n" + (format_hits(lis_hits) if lis_hits else "_None_"))
    if caps.code:
        sections.append("## Code\n" + (format_hits(code_hits) if code_hits else "_None_"))
    sections.extend(
        [
            "## Files to read first\n"
            + ("\n".join(f"- {f}" for f in files) if files else "_None_"),
            "## Gaps\n"
            + ("\n".join(f"- {g}" for g in gaps) if gaps else "- None detected"),
        ]
    )
    return "\n\n".join(sections)


def _ranked_files(hits: list[Any]) -> list[str]:
    best: dict[str, float] = {}
    for hit in hits:
        payload = hit.payload or {}
        path = payload.get("file")
        if not path:
            continue
        score = float(getattr(hit, "score", 0.0) or 0.0)
        if path not in best or score > best[path]:
            best[path] = score
    return [p for p, _ in sorted(best.items(), key=lambda item: item[1], reverse=True)]
