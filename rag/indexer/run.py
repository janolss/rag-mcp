"""Full-rebuild and partial-file indexing pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.indexer.chunk_code import chunk_code
from rag.indexer.chunk_markdown import chunk_markdown
from rag.indexer.collections import CollectionRouter
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
            language=meta.get("language"),
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
            # Default legacy workspace/source; multi-workspace callers override.
            "workspace_id": "default",
            "source_id": bucket or meta["type"] or "default",
        }
        for key in ("symbol", "symbol_kind", "chunk_key", "imports"):
            if key in piece:
                chunk[key] = piece[key]
        chunk.update(lis_fields)
        chunks.append(chunk)
    # Line numbers relative to the text that was chunked (body without frontmatter for LIS)
    attach_line_numbers(body, chunks)
    return chunks


def _registered_extra_roots(config: Config) -> list[Path]:
    """Absolute LIS (and future external) roots that are explicitly configured."""
    roots: list[Path] = []
    for pattern in config.index.lis:
        path = Path(pattern)
        if not path.is_absolute():
            continue
        # For globs like /mirror/docs/**/*.md, register the stable parent prefix.
        parts = path.parts
        if "**" in parts:
            roots.append(Path(*parts[: parts.index("**")]))
        else:
            roots.append(path.parent if path.suffix else path)
    return roots


def build_chunks(config: Config) -> list[dict[str, Any]]:
    repo_root = config.repo_root_path
    specs = selected_sources_for_config(config)
    files = walk_files(
        repo_root,
        specs,
        config.index.ignore_dirs,
        extra_roots=_registered_extra_roots(config),
    )
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
        from rag.security.paths import PathSecurityPolicy, SecurePathError, assert_within_roots

        policy = PathSecurityPolicy()
        roots = [repo_root.resolve(), *[r.resolve() for r in _registered_extra_roots(config)]]
        try:
            if path.is_absolute():
                path = assert_within_roots(path, roots, policy=policy)
                identity = file_identity(path, repo_root)
            else:
                rel = raw_norm.lstrip("./")
                path = assert_within_roots(repo_root / rel, roots, policy=policy)
                identity = rel
        except SecurePathError as exc:
            raise RuntimeError(str(exc)) from exc

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

    router = CollectionRouter(config)
    staging = router.staging_collection()
    previous_active = router.active_collection()
    staging_config = _config_with_collection(config, staging)

    store = VectorStore(staging_config)
    try:
        store.recreate_collection(vector_size)
        texts = [c["content"] for c in chunks]
        logger.info(
            "Embedding %d chunks into staging '%s' (concurrency=%d)",
            len(texts),
            staging,
            max(1, int(config.embedding.concurrency or 1)),
        )
        vectors = embedder.embed_texts(texts, for_query=False)
        count = store.upsert_chunks(chunks, vectors)
        if count <= 0:
            raise RuntimeError("staging index produced zero points; active index unchanged")
    except Exception:
        store.close()
        logger.exception(
            "Full index failed before activation; active collection remains %s",
            previous_active,
        )
        raise
    else:
        store.close()
        router.activate(staging, vector_size=vector_size)

    status = _status_base(config, chunk_count=count, vector_size=vector_size)
    status["index_mode"] = "full"
    status["active_collection"] = router.active_collection()
    status["previous_collection"] = previous_active
    from rag.indexer.index_manifest import current_manifest, write_manifest

    manifest = current_manifest(
        embedding_model=config.embedding.model,
        vector_size=vector_size,
        collection=router.active_collection(),
    )
    write_manifest(config.status_file_path.with_name("index_manifest.json"), manifest)
    status["index_manifest"] = manifest.to_dict()
    _write_status(config.status_file_path, status)
    logger.info("Indexed %d chunks into '%s'", count, router.active_collection())
    return status


def _config_with_collection(config: Config, collection: str) -> Config:
    """Shallow-copy config pointing VectorStore at another collection name."""
    from copy import deepcopy

    cloned = deepcopy(config)
    cloned.qdrant.collection = collection
    return cloned


def run_index_files(config: Config, rel_paths: Sequence[str]) -> dict[str, Any]:
    """Upsert chunks for specific files using the incremental registry flow."""
    from rag.indexer.incremental import run_incremental

    normalized = [p.replace("\\", "/").lstrip("./") for p in rel_paths if p and p.strip()]
    if not normalized:
        raise RuntimeError("No files provided for partial index")

    stats = run_incremental(config, list(normalized))
    status = _status_base(
        config,
        chunk_count=int(stats.get("points_count") or 0),
        vector_size=int((read_status(config) or {}).get("vector_size") or 0),
    )
    status["index_mode"] = "partial"
    status["last_indexed_files"] = normalized
    status["incremental"] = stats
    _write_status(config.status_file_path, status)
    logger.info("Incremental index stats: %s", stats)
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
