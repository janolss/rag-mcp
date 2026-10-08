"""Full-rebuild and partial-file indexing pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.indexer.chunk_code import chunk_code
from rag.indexer.chunk_markdown import chunk_markdown
from rag.indexer.frontmatter import lis_fields_from_frontmatter, split_frontmatter
from rag.indexer.git_info import git_head_sha
from rag.indexer.line_ranges import attach_line_numbers
from rag.indexer.metadata import metadata_from_path
from rag.indexer.requirement_ids import extract_requirement_ids
from rag.indexer.sources import selected_sources_for_config
from rag.indexer.walk import file_identity, read_text_file, walk_files
from rag.store import VectorStore

logger = logging.getLogger(__name__)


def _chunk_file(
    config: Config,
    path: Path,
    rel: str,
    *,
    bucket: str | None = None,
) -> list[dict[str, Any]]:
    meta = metadata_from_path(rel, config.index, bucket=bucket)
    text = read_text_file(path)
    if not text.strip():
        return []

    lis_fields: dict[str, str] = {}
    body = text
    if meta["type"] == "lis":
        fm, body = split_frontmatter(text)
        lis_fields = lis_fields_from_frontmatter(fm)
        if not body.strip():
            return []

    if meta["type"] in {"documentation", "lis"} or path.suffix.lower() == ".md":
        pieces = chunk_markdown(
            body,
            chunk_size=config.index.chunk_size,
            chunk_overlap=config.index.chunk_overlap,
        )
    else:
        pieces = chunk_code(
            body,
            chunk_size=config.index.chunk_size,
            chunk_overlap=config.index.chunk_overlap,
        )

    patterns = config.index.requirement_id_patterns
    chunks: list[dict[str, Any]] = []
    for index, piece in enumerate(pieces):
        content = piece["content"]
        section = piece.get("section")
        id_source = content if not section else f"{section}\n{content}"
        chunk: dict[str, Any] = {
            "type": meta["type"],
            "app": meta["app"],
            "file": meta["file"],
            "language": meta["language"],
            "section": section,
            "chunk_index": index,
            "content": content,
            "requirement_ids": extract_requirement_ids(id_source, patterns),
        }
        chunk.update(lis_fields)
        chunks.append(chunk)
    # Line numbers relative to the text that was chunked (body without frontmatter for LIS)
    attach_line_numbers(body, chunks)
    return chunks


def build_chunks(config: Config) -> list[dict[str, Any]]:
    repo_root = config.repo_root_path
    specs = selected_sources_for_config(config)
    files = walk_files(repo_root, specs, config.index.ignore_dirs)
    chunks: list[dict[str, Any]] = []

    for path, bucket in files:
        rel = file_identity(path, repo_root)
        chunks.extend(_chunk_file(config, path, rel, bucket=bucket))

    logger.info("Built %d chunks from %d files", len(chunks), len(files))
    return chunks


def build_chunks_for_files(config: Config, rel_paths: Sequence[str]) -> list[dict[str, Any]]:
    """Build chunks for explicit paths (repo-relative or absolute)."""
    repo_root = config.repo_root_path
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in rel_paths:
        raw_norm = raw.replace("\\", "/").strip()
        if not raw_norm:
            continue
        path = Path(raw_norm)
        if path.is_absolute():
            path = path.resolve()
            identity = file_identity(path, repo_root)
        else:
            rel = raw_norm.lstrip("./")
            path = (repo_root / rel).resolve()
            try:
                path.relative_to(repo_root.resolve())
            except ValueError as exc:
                raise RuntimeError(f"Path escapes repo_root: {raw}") from exc
            identity = rel

        if identity in seen:
            continue
        seen.add(identity)
        if not path.is_file():
            logger.warning("Skipping missing file for partial index: %s", identity)
            continue
        # Infer lis bucket when path matches a configured lis glob identity prefix
        bucket = _infer_bucket(config, identity, path)
        chunks.extend(_chunk_file(config, path, identity, bucket=bucket))

    logger.info("Built %d chunks from %d requested files", len(chunks), len(seen))
    return chunks


def _infer_bucket(config: Config, identity: str, path: Path) -> str | None:
    """Best-effort bucket for partial index paths."""
    from rag.indexer.walk import expand_glob

    enabled = config.enabled_buckets()
    resolved = path.resolve()
    if "lis" in enabled and config.index.lis:
        for pattern in config.index.lis:
            if resolved in {p.resolve() for p in expand_glob(config.repo_root_path, pattern)}:
                return "lis"
        try:
            resolved.relative_to(config.repo_root_path.resolve())
        except ValueError:
            # Explicit absolute path outside repo while LIS is enabled
            return "lis"
    if "knowledge" in enabled and (
        identity.lower().endswith("readme.md")
        or any(
            identity.startswith(p if p.endswith("/") else f"{p}/")
            for p in config.index.documentation_prefixes
        )
    ):
        return "knowledge"
    if "code" in enabled:
        return "code"
    return None


def _status_base(config: Config, *, chunk_count: int, vector_size: int) -> dict[str, Any]:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model": config.embedding.model,
        "embedding_base_url": config.embedding.base_url,
        "collection": config.qdrant.collection,
        "qdrant_mode": config.qdrant.mode,
        "sources": config.index.sources,
        "enabled_buckets": sorted(config.enabled_buckets()),
        "capabilities": {
            "knowledge": config.mcp.capabilities.knowledge,
            "code": config.mcp.capabilities.code,
            "lis": config.mcp.capabilities.lis,
        },
        "chunk_count": chunk_count,
        "vector_size": vector_size,
        "repo_root": str(config.repo_root_path),
        "git_sha": git_head_sha(config.repo_root_path),
        "requirement_id_patterns": list(config.index.requirement_id_patterns),
    }


def run_index(config: Config) -> dict[str, Any]:
    embedder = EmbeddingClient(config.embedding)
    ok, message = embedder.health_check()
    if not ok:
        raise RuntimeError(f"Embedding endpoint unhealthy: {message}")
    logger.info("Embedding health: %s", message)

    chunks = build_chunks(config)
    if not chunks:
        raise RuntimeError("No chunks produced — check index.sources and repo_root")

    sample_vector = embedder.embed_texts([chunks[0]["content"]], for_query=False)[0]
    vector_size = len(sample_vector)

    store = VectorStore(config)
    try:
        store.recreate_collection(vector_size)

        texts = [c["content"] for c in chunks]
        logger.info(
            "Embedding %d chunks (concurrency=%d)",
            len(texts),
            max(1, int(config.embedding.concurrency or 1)),
        )
        vectors = embedder.embed_texts(texts, for_query=False)

        count = store.upsert_chunks(chunks, vectors)
    finally:
        store.close()

    status = _status_base(config, chunk_count=count, vector_size=vector_size)
    status["index_mode"] = "full"
    _write_status(config.status_file_path, status)
    logger.info("Indexed %d chunks into '%s'", count, config.qdrant.collection)
    return status


def run_index_files(config: Config, rel_paths: Sequence[str]) -> dict[str, Any]:
    """Upsert chunks for specific files without recreating the collection."""
    embedder = EmbeddingClient(config.embedding)
    ok, message = embedder.health_check()
    if not ok:
        raise RuntimeError(f"Embedding endpoint unhealthy: {message}")

    normalized = [p.replace("\\", "/").lstrip("./") for p in rel_paths if p and p.strip()]
    if not normalized:
        raise RuntimeError("No files provided for partial index")

    chunks = build_chunks_for_files(config, normalized)
    if not chunks:
        raise RuntimeError("No chunks produced for the given files")

    sample_vector = embedder.embed_texts([chunks[0]["content"]], for_query=False)[0]
    vector_size = len(sample_vector)
    files_touched = sorted({c["file"] for c in chunks})

    store = VectorStore(config)
    try:
        store.ensure_collection(vector_size)
        store.delete_by_files(files_touched)
        vectors = embedder.embed_texts([c["content"] for c in chunks], for_query=False)
        count = store.upsert_chunks(chunks, vectors)
        points = store.count()
    finally:
        store.close()

    prior = read_status(config) or {}
    status = _status_base(config, chunk_count=points, vector_size=vector_size)
    status["index_mode"] = "partial"
    status["last_indexed_files"] = files_touched
    status["partial_upsert_count"] = count
    # Preserve full-index vector_size hint if prior had one and counts differ oddly
    if prior.get("vector_size") and prior.get("vector_size") != vector_size:
        status["warning"] = (
            f"Partial index vector_size={vector_size} differs from prior "
            f"{prior.get('vector_size')}; run a full index if search fails."
        )
    _write_status(config.status_file_path, status)
    logger.info(
        "Partial index upserted %d chunks for %d files into '%s'",
        count,
        len(files_touched),
        config.qdrant.collection,
    )
    return status


def read_status(config: Config) -> dict[str, Any] | None:
    path = config.status_file_path
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def status_report(config: Config) -> dict[str, Any]:
    file_status = read_status(config)
    store = VectorStore(config)
    try:
        points = store.count()
        exists = store.collection_exists()
    finally:
        store.close()

    report: dict[str, Any] = {
        "collection_exists": exists,
        "points_count": points,
        "status_file": str(config.status_file_path),
        "configured_model": config.embedding.model,
        "index_status": file_status,
    }
    if file_status and file_status.get("model") != config.embedding.model:
        report["warning"] = (
            f"Index was built with model {file_status.get('model')!r} but config "
            f"uses {config.embedding.model!r}. Re-run index after changing models."
        )

    if not file_status or not file_status.get("updated_at"):
        report["stale_hint"] = "No index status file; run: python -m rag.cli index"
    elif points == 0:
        report["stale_hint"] = "Collection is empty; run: python -m rag.cli index"
    elif file_status.get("index_mode") == "partial":
        report["stale_hint"] = (
            "Last update was a partial file index; run a full index after large refactors."
        )

    return report


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)
        fh.write("\n")
