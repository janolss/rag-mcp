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
from rag.indexer.source_model import (
    discover_workspace_files,
    registered_source_roots,
    resolve_workspace_sources,
)
from rag.indexer.walk import file_identity, path_identity_for_indexing, read_text_file
from rag.store import VectorStore
from rag.workspaces import WorkspaceRegistry

logger = logging.getLogger(__name__)


def _chunk_file(
    config: Config,
    path: Path,
    rel: str,
    *,
    bucket: str | None = None,
    workspace_id: str = "default",
    source_id: str | None = None,
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
    resolved_source = source_id or bucket or meta["type"] or "default"
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
            "workspace_id": workspace_id,
            "source_id": resolved_source,
        }
        for key in ("symbol", "symbol_kind", "chunk_key", "imports"):
            if key in piece:
                chunk[key] = piece[key]
        chunk.update(lis_fields)
        chunks.append(chunk)
    # Line numbers relative to the text that was chunked (body without frontmatter for LIS)
    attach_line_numbers(body, chunks)
    return chunks


def _registered_extra_roots(
    config: Config,
    *,
    workspace_id: str | None = None,
) -> list[Path]:
    """Registered source roots plus absolute LIS globs from legacy config."""
    roots: list[Path] = list(registered_source_roots(config, workspace_id=workspace_id))
    seen = {root.resolve() for root in roots}
    for pattern in config.index.lis:
        path = Path(pattern)
        if not path.is_absolute():
            continue
        # For globs like /mirror/docs/**/*.md, register the stable parent prefix.
        parts = path.parts
        if "**" in parts:
            candidate = Path(*parts[: parts.index("**")])
        else:
            candidate = path.parent if path.suffix else path
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _resolve_index_workspace_ids(
    config: Config,
    workspace_id: str | None,
) -> list[str]:
    registry = WorkspaceRegistry.from_config(config)
    ids = registry.ids()
    if workspace_id is None or workspace_id == "*":
        return ids
    registry.get(workspace_id)  # raise if unknown
    return [workspace_id]


def build_chunks(
    config: Config,
    *,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build chunks by walking registered Source roots for one or all workspaces.

    When ``workspace_id`` is omitted and multiple workspaces exist, chunks for
    every registered workspace are included (safe full rebuild).
    """
    target_ids = _resolve_index_workspace_ids(config, workspace_id)
    chunks: list[dict[str, Any]] = []
    file_count = 0

    for wid in target_ids:
        files = discover_workspace_files(config, workspace_id=wid)
        file_count += len(files)
        for path, source_id, bucket, identity in files:
            chunks.extend(
                _chunk_file(
                    config,
                    path,
                    identity,
                    bucket=bucket,
                    workspace_id=wid,
                    source_id=source_id,
                )
            )

    logger.info(
        "Built %d chunks from %d files across workspaces %s",
        len(chunks),
        file_count,
        target_ids,
    )
    return chunks


def build_chunks_for_files(
    config: Config,
    rel_paths: Sequence[str],
    *,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build chunks for explicit paths (repo-relative or absolute)."""
    workspace, sources = resolve_workspace_sources(config, workspace_id=workspace_id)
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
        roots = [
            repo_root.resolve(),
            *[r.resolve() for r in _registered_extra_roots(config, workspace_id=workspace.id)],
        ]
        try:
            if path.is_absolute():
                path = assert_within_roots(path, roots, policy=policy)
            else:
                rel = raw_norm.lstrip("./")
                path = assert_within_roots(repo_root / rel, roots, policy=policy)
        except SecurePathError as exc:
            raise RuntimeError(str(exc)) from exc

        source_id, bucket, matched_source = _match_source_for_path(sources, path, config)
        identity = path_identity_for_indexing(
            path,
            workspace_root=workspace.root_path,
            source_root=matched_source.root if matched_source is not None else None,
            repo_root=repo_root,
        )
        if identity in seen:
            continue
        seen.add(identity)
        if not path.is_file():
            logger.warning("Skipping missing file for partial index: %s", identity)
            continue
        chunks.extend(
            _chunk_file(
                config,
                path,
                identity,
                bucket=bucket,
                workspace_id=workspace.id,
                source_id=source_id,
            )
        )

    logger.info("Built %d chunks from %d requested files", len(chunks), len(seen))
    return chunks


def _match_source_for_path(
    sources: tuple,
    path: Path,
    config: Config,
) -> tuple[str, str | None, Any]:
    """Pick the best Source for an explicit path; fall back to legacy bucket inference."""
    from rag.domain.models import Source

    resolved = path.resolve()
    # Prefer the longest matching source root (nested sources win).
    matched: Source | None = None
    matched_len = -1
    for source in sources:
        root = Path(source.root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        root_len = len(root.parts)
        if root_len > matched_len:
            matched = source
            matched_len = root_len
    if matched is not None:
        return matched.id, matched.bucket or matched.id, matched
    identity = file_identity(path, config.repo_root_path)
    bucket = _infer_bucket(config, identity, path)
    return (bucket or "default"), bucket, None


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


def run_index(config: Config, *, workspace_id: str | None = None) -> dict[str, Any]:
    """
    Full index for one workspace or all registered workspaces.

    When a single workspace is requested among several peers, vectors for that
    workspace are replaced in the active collection so sibling workspaces are
    preserved. Otherwise a staging rebuild swaps the whole shared collection.
    """
    embedder = EmbeddingClient(config.embedding)
    ok, message = embedder.health_check()
    if not ok:
        raise RuntimeError(f"Embedding endpoint unhealthy: {message}")
    logger.info("Embedding health: %s", message)

    target_ids = _resolve_index_workspace_ids(config, workspace_id)
    registry = WorkspaceRegistry.from_config(config)
    scoped_single = (
        workspace_id is not None
        and workspace_id != "*"
        and len(registry.ids()) > 1
        and len(target_ids) == 1
    )

    chunks = build_chunks(config, workspace_id=workspace_id)
    if not chunks:
        raise RuntimeError("No chunks produced — check workspace sources / index.sources and roots")

    sample_vector = embedder.embed_texts([chunks[0]["content"]], for_query=False)[0]
    vector_size = len(sample_vector)

    if scoped_single:
        return _run_index_workspace_inplace(
            config,
            embedder=embedder,
            chunks=chunks,
            workspace_id=target_ids[0],
            vector_size=vector_size,
        )

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
    status["workspace_ids"] = target_ids
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


def _run_index_workspace_inplace(
    config: Config,
    *,
    embedder: EmbeddingClient,
    chunks: list[dict[str, Any]],
    workspace_id: str,
    vector_size: int,
) -> dict[str, Any]:
    """Replace one workspace's vectors without wiping peer workspaces."""
    router = CollectionRouter(config)
    store = VectorStore(config)
    try:
        store.ensure_collection(vector_size)
        store.delete_by_workspace(workspace_id)
        texts = [c["content"] for c in chunks]
        logger.info(
            "Embedding %d chunks for workspace %s into active '%s'",
            len(texts),
            workspace_id,
            router.active_collection(),
        )
        vectors = embedder.embed_texts(texts, for_query=False)
        count = store.upsert_chunks(chunks, vectors)
        if count <= 0:
            raise RuntimeError(f"workspace index for {workspace_id!r} produced zero points")
        points = store.count()
    finally:
        store.close()

    status = _status_base(config, chunk_count=points, vector_size=vector_size)
    status["index_mode"] = "workspace"
    status["workspace_id"] = workspace_id
    status["workspace_ids"] = [workspace_id]
    status["workspace_chunk_count"] = count
    status["active_collection"] = router.active_collection()
    _write_status(config.status_file_path, status)
    logger.info(
        "Indexed %d chunks for workspace %s into '%s'",
        count,
        workspace_id,
        router.active_collection(),
    )
    return status


def _config_with_collection(config: Config, collection: str) -> Config:
    """Shallow-copy config pointing VectorStore at another collection name."""
    from copy import deepcopy

    cloned = deepcopy(config)
    cloned.qdrant.collection = collection
    return cloned


def run_index_files(
    config: Config,
    rel_paths: Sequence[str],
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Upsert chunks for specific files using the incremental registry flow."""
    from rag.indexer.incremental import run_incremental

    normalized = [p.replace("\\", "/").lstrip("./") for p in rel_paths if p and p.strip()]
    if not normalized:
        raise RuntimeError("No files provided for partial index")

    workspace, _sources = resolve_workspace_sources(config, workspace_id=workspace_id)
    stats = run_incremental(config, list(normalized), workspace_id=workspace.id)
    status = _status_base(
        config,
        chunk_count=int(stats.get("points_count") or 0),
        vector_size=int((read_status(config) or {}).get("vector_size") or 0),
    )
    status["index_mode"] = "partial"
    status["workspace_id"] = workspace.id
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
