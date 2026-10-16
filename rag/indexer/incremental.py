"""Write-verify-retire incremental indexing transactions."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.indexer.document_registry import DocumentRecord, DocumentRegistry
from rag.indexer.inventory import (
    InventoryDiff,
    ObservedDocument,
    inventory_for_files,
    inventory_for_workspace,
)
from rag.store import VectorStore

logger = logging.getLogger(__name__)


class IncrementalIndexError(RuntimeError):
    """Raised when a document write transaction fails verification."""


def registry_path_for(config: Config) -> Path:
    return config.status_file_path.parent / "document_registry.sqlite3"


def run_incremental(
    config: Config,
    rel_paths: list[str] | None = None,
    *,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Entry point used by ``index --files`` and full incremental passes."""
    from rag.indexer.source_model import resolve_workspace_sources

    embedder = EmbeddingClient(config.embedding)
    ok, message = embedder.health_check()
    if not ok:
        raise RuntimeError(f"Embedding endpoint unhealthy: {message}")

    workspace, _sources = resolve_workspace_sources(config, workspace_id=workspace_id)
    registry = DocumentRegistry(registry_path_for(config))
    if rel_paths:
        diff = inventory_for_files(config, registry, rel_paths, workspace_id=workspace.id)
    else:
        diff = inventory_for_workspace(config, registry, workspace_id=workspace.id)

    return apply_inventory(config, registry, diff, embedder=embedder)


def apply_inventory(
    config: Config,
    registry: DocumentRegistry,
    diff: InventoryDiff,
    *,
    embedder: EmbeddingClient | None = None,
) -> dict[str, Any]:
    embedder = embedder or EmbeddingClient(config.embedding)
    stats: dict[str, Any] = {
        "new": len(diff.new),
        "changed": len(diff.changed),
        "unchanged": len(diff.unchanged),
        "deleted": len(diff.deleted),
        "upserted_chunks": 0,
        "embedded_chunks": 0,
    }
    store = VectorStore(config)
    try:
        probe = embedder.embed_texts(["probe"], for_query=False)[0]
        store.ensure_collection(len(probe))

        # Unchanged: skip embeddings entirely (idempotent re-run).
        for observed, previous in diff.unchanged:
            registry.upsert(
                DocumentRecord(
                    workspace_id=observed.workspace_id,
                    source_id=observed.source_id,
                    document_id=observed.document_id,
                    content_hash=previous.content_hash,
                    revision=previous.revision,
                    status="active",
                    observed_at=time.time(),
                    path=observed.path,
                )
            )
            logger.info("Skipping unchanged document %s", observed.document_id)

        prev_by_id = {obs.document_id: prev for obs, prev in diff.changed}
        for observed in [*diff.new, *[item for item, _prev in diff.changed]]:
            count = write_verify_retire_document(
                config,
                store,
                registry,
                embedder,
                observed=observed,
                previous=prev_by_id.get(observed.document_id),
            )
            stats["upserted_chunks"] += count
            stats["embedded_chunks"] += count

        for deleted in diff.deleted:
            retire_deleted_document(store, registry, deleted)

        stats["points_count"] = store.count()
    finally:
        store.close()
    return stats


def write_verify_retire_document(
    config: Config,
    store: VectorStore,
    registry: DocumentRegistry,
    embedder: EmbeddingClient,
    *,
    observed: ObservedDocument,
    previous: DocumentRecord | None,
) -> int:
    """
    Safely replace one document's vectors.

    Order: mark writing → upsert → verify → retire orphans → mark ready.
    On failure before verify, restore the previous registry snapshot.
    """
    path = observed.absolute_path
    if path is None:
        path = Path(observed.path)
        if not path.is_absolute():
            path = (config.repo_root_path / observed.path).resolve()
    if not path.is_file():
        raise IncrementalIndexError(f"missing file for document {observed.document_id!r}")

    from rag.indexer.run import _chunk_file

    prior_snapshot = previous
    if previous and previous.status == "writing":
        revision = previous.revision
    else:
        revision = (previous.revision + 1) if previous else 1

    registry.upsert(
        DocumentRecord(
            workspace_id=observed.workspace_id,
            source_id=observed.source_id,
            document_id=observed.document_id,
            content_hash=observed.content_hash,
            revision=revision,
            status="writing",
            observed_at=time.time(),
            path=observed.path,
        )
    )

    chunks = _chunk_file(
        config,
        path,
        observed.path,
        bucket=observed.source_id,
        workspace_id=observed.workspace_id,
        source_id=observed.source_id,
    )
    for chunk in chunks:
        chunk["workspace_id"] = observed.workspace_id
        chunk["source_id"] = observed.source_id
        chunk["revision"] = revision

    if not chunks:
        registry.upsert(
            DocumentRecord(
                workspace_id=observed.workspace_id,
                source_id=observed.source_id,
                document_id=observed.document_id,
                content_hash=observed.content_hash,
                revision=revision,
                status="active",
                observed_at=time.time(),
                path=observed.path,
            )
        )
        return 0

    new_point_ids: set[str] = set()
    try:
        from rag.indexer.payload import build_payload

        for chunk in chunks:
            payload = build_payload(
                chunk,
                workspace_id=observed.workspace_id,
                source_id=observed.source_id,
                revision=revision,
            )
            new_point_ids.add(str(payload["point_id"]))

        vectors = embedder.embed_texts([c["content"] for c in chunks], for_query=False)
        upserted = store.upsert_chunks(chunks, vectors)
        if upserted <= 0:
            raise IncrementalIndexError("upsert produced zero points")

        verified = store.scroll_document_points(
            workspace_id=observed.workspace_id,
            source_id=observed.source_id,
            document_id=observed.document_id,
            revision=revision,
        )
        if len(verified) < len(chunks):
            raise IncrementalIndexError(
                f"verification failed for {observed.document_id!r} revision={revision}"
            )

        store.delete_document_points_except(
            workspace_id=observed.workspace_id,
            source_id=observed.source_id,
            document_id=observed.document_id,
            keep_point_ids=new_point_ids,
        )
    except Exception:
        if prior_snapshot is not None:
            registry.restore(prior_snapshot)
        else:
            registry.mark_deleted(observed.workspace_id, observed.source_id, observed.document_id)
        raise

    registry.upsert(
        DocumentRecord(
            workspace_id=observed.workspace_id,
            source_id=observed.source_id,
            document_id=observed.document_id,
            content_hash=observed.content_hash,
            revision=revision,
            status="active",
            observed_at=time.time(),
            path=observed.path,
        )
    )
    return len(chunks)


def retire_deleted_document(
    store: VectorStore,
    registry: DocumentRegistry,
    record: DocumentRecord,
) -> None:
    """Delete vectors for a verified-missing document, then tombstone the registry."""
    store.delete_by_document(
        workspace_id=record.workspace_id,
        source_id=record.source_id,
        document_id=record.document_id,
    )
    # Fallback for legacy points keyed only by file path.
    store.delete_by_files(
        [record.path or record.document_id],
        workspace_id=record.workspace_id,
        allow_legacy=True,
    )
    registry.mark_deleted(record.workspace_id, record.source_id, record.document_id)
    logger.info("Retired deleted document %s", record.document_id)


def run_incremental_files(
    config: Config,
    rel_paths: Sequence[str],
    *,
    store: VectorStore | None = None,
    embedder: EmbeddingClient | None = None,
    registry: DocumentRegistry | None = None,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Convenience wrapper kept for callers that already opened a store."""
    del store  # apply_inventory opens its own store for transactional clarity
    reg = registry or DocumentRegistry(registry_path_for(config))
    emb = embedder or EmbeddingClient(config.embedding)
    diff = inventory_for_files(config, reg, rel_paths, workspace_id=workspace_id)
    return apply_inventory(config, reg, diff, embedder=emb)
