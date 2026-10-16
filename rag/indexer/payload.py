"""Versioned Qdrant payload construction."""

from __future__ import annotations

from typing import Any

from rag.indexer.identity import (
    PAYLOAD_SCHEMA_VERSION,
    build_chunk_identity,
    content_hash,
)


def build_payload(
    chunk: dict[str, Any],
    *,
    workspace_id: str,
    source_id: str,
    revision: int = 1,
) -> dict[str, Any]:
    """Build a versioned payload; content hash is separate from identity."""
    # Prefer explicit document IDs (e.g. LIS frontmatter) over file paths.
    document_key = str(chunk.get("document_id") or chunk.get("file") or "")
    identity = build_chunk_identity(
        workspace_id=workspace_id,
        source_id=source_id,
        document_path=document_key,
        chunk_index=int(chunk.get("chunk_index") or 0),
        section=chunk.get("section"),
        symbol=chunk.get("symbol"),
    )
    payload: dict[str, Any] = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "source_id": source_id,
        "document_id": identity.document.document_id,
        "chunk_key": identity.chunk_key,
        "chunk_index": identity.chunk_index,
        "content_hash": content_hash(str(chunk.get("content") or "")),
        "revision": revision,
        "type": chunk.get("type"),
        "app": chunk.get("app"),
        "file": chunk.get("file"),
        "language": chunk.get("language"),
        "section": chunk.get("section"),
        "content": chunk.get("content"),
        "requirement_ids": list(chunk.get("requirement_ids") or []),
        "point_id": identity.point_id,
    }
    for key in (
        "doc_type",
        "process_area",
        "domain",
        "status",
        "title",
        "symbol",
        "start_line",
        "end_line",
    ):
        value = chunk.get(key)
        if value is not None and value != "":
            payload[key] = value
    return payload


def is_legacy_payload(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return True
    return int(payload.get("schema_version") or 0) < PAYLOAD_SCHEMA_VERSION
