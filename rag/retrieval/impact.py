"""Impact analysis and heuristic coverage gaps."""

from __future__ import annotations

import re
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.retrieval.search import format_hits, search_hits, validate_app
from rag.store import QdrantLockError, VectorStore

_PATH_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".md",
    ".ejs",
    ".json",
    ".yml",
    ".yaml",
)


def looks_like_path(value: str) -> bool:
    text = (value or "").strip()
    if not text or "\n" in text or len(text) > 260:
        return False
    normalized = text.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if any(normalized.endswith(suf) for suf in _PATH_SUFFIXES):
        return True
    return "/" in normalized and " " not in normalized


def impact_of_change(
    config: Config,
    change: str,
    *,
    app: str | None = None,
    path_prefix: str | None = None,
    top_k: int = 8,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    change = (change or "").strip()
    if not change:
        return "Error: change cannot be empty."

    try:
        app_filter = validate_app(config, app)
    except ValueError as exc:
        return f"Error: {exc}"

    effective_prefix = path_prefix
    query = change
    if looks_like_path(change):
        path = change.replace("\\", "/").lstrip("./")
        query = path
        if not effective_prefix and "/" in path:
            effective_prefix = path.rsplit("/", 1)[0] + "/"

    owns_store = store is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)

        code_hits = search_hits(
            config,
            query,
            type_filter=["code"],
            app_filter=app_filter,
            path_prefix=effective_prefix,
            top_k=top_k,
            store=store,
            embedder=embedder,
        )
        test_hits = search_hits(
            config,
            query,
            type_filter=["test"],
            app_filter=app_filter,
            path_prefix=effective_prefix,
            top_k=top_k,
            store=store,
            embedder=embedder,
        )
        doc_hits = search_hits(
            config,
            query,
            type_filter=["documentation"],
            path_prefix=path_prefix,
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

    risks: list[str] = []
    if not code_hits:
        risks.append("No likely code hits — change description may be too vague or index stale")
    if not doc_hits:
        risks.append("No related documentation/requirements found")
    if not test_hits:
        risks.append("No nearby tests found — consider adding coverage")

    return "\n\n".join(
        [
            f"## Change\n{change}",
            "## Likely affected code\n"
            + (format_hits(code_hits) if code_hits else "_None_"),
            "## Related requirements/docs\n"
            + (format_hits(doc_hits) if doc_hits else "_None_"),
            "## Suggested tests\n" + (format_hits(test_hits) if test_hits else "_None_"),
            "## Risk notes\n"
            + ("\n".join(f"- {r}" for r in risks) if risks else "- None flagged"),
        ]
    )


def find_gaps(
    config: Config,
    area: str,
    *,
    app: str | None = None,
    top_k: int = 10,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
) -> str:
    area = (area or "").strip()
    if not area:
        return "Error: area cannot be empty."

    try:
        app_filter = validate_app(config, app)
    except ValueError as exc:
        return f"Error: {exc}"

    threshold = config.search.score_threshold
    owns_store = store is None
    try:
        store = store or VectorStore(config)
        embedder = embedder or EmbeddingClient(config.embedding)

        doc_hits = search_hits(
            config,
            area,
            type_filter=["documentation"],
            top_k=top_k,
            store=store,
            embedder=embedder,
        )
        code_hits = search_hits(
            config,
            area,
            type_filter=["code", "test"],
            app_filter=app_filter,
            top_k=top_k,
            store=store,
            embedder=embedder,
        )

        doc_without_code: list[str] = []
        probes = _doc_probes(doc_hits, limit=8)
        for label, probe in probes:
            related = search_hits(
                config,
                probe,
                type_filter=["code", "test"],
                app_filter=app_filter,
                top_k=3,
                store=store,
                embedder=embedder,
            )
            best = max((float(getattr(h, "score", 0.0) or 0.0) for h in related), default=0.0)
            if best < threshold:
                doc_without_code.append(f"{label} (best code score {best:.3f} < {threshold})")

        code_without_docs: list[str] = []
        for hit in code_hits[:8]:
            payload = hit.payload or {}
            label = payload.get("file", "?")
            probe = (payload.get("section") or payload.get("content") or label)[:240]
            related = search_hits(
                config,
                probe,
                type_filter=["documentation"],
                top_k=3,
                store=store,
                embedder=embedder,
            )
            best = max((float(getattr(h, "score", 0.0) or 0.0) for h in related), default=0.0)
            if best < threshold:
                code_without_docs.append(f"{label} (best docs score {best:.3f} < {threshold})")
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except RuntimeError as exc:
        return f"Error: {exc}"
    finally:
        if owns_store and store is not None:
            store.close()

    # Cap readability
    doc_without_code = doc_without_code[:15]
    code_without_docs = code_without_docs[:15]

    return "\n\n".join(
        [
            f"## Area\n{area}",
            "## Documentation without clear code\n"
            + (
                "\n".join(f"- {x}" for x in doc_without_code)
                if doc_without_code
                else "- None flagged"
            ),
            "## Code without clear documentation\n"
            + (
                "\n".join(f"- {x}" for x in code_without_docs)
                if code_without_docs
                else "- None flagged"
            ),
            "## Note\nfind_gaps is heuristic (score thresholds), not complete coverage proof.",
        ]
    )


def _doc_probes(doc_hits: list[Any], *, limit: int) -> list[tuple[str, str]]:
    probes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for hit in doc_hits:
        payload = hit.payload or {}
        req_ids = payload.get("requirement_ids") or []
        for req_id in req_ids:
            key = f"id:{req_id}"
            if key not in seen:
                seen.add(key)
                probes.append((req_id, req_id))
        section = payload.get("section")
        file_path = payload.get("file", "?")
        if section:
            key = f"section:{section}"
            if key not in seen:
                seen.add(key)
                probes.append((f"{file_path} § {section}", section))
        else:
            snippet = re.sub(r"\s+", " ", (payload.get("content") or "")[:160]).strip()
            if snippet:
                key = f"file:{file_path}:{snippet[:40]}"
                if key not in seen:
                    seen.add(key)
                    probes.append((file_path, snippet))
        if len(probes) >= limit:
            break
    return probes
