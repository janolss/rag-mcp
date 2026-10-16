"""Stable document and chunk identity helpers independent of content hash."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rag.store import make_point_id

PAYLOAD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DocumentIdentity:
    workspace_id: str
    source_id: str
    document_id: str

    @property
    def key(self) -> str:
        return f"{self.workspace_id}|{self.source_id}|{self.document_id}"


@dataclass(frozen=True)
class ChunkKey:
    document: DocumentIdentity
    chunk_key: str
    chunk_index: int = 0

    @property
    def point_id(self) -> str:
        return make_point_id(
            self.document.workspace_id,
            self.document.source_id,
            self.document.document_id,
            self.chunk_key,
            str(self.chunk_index),
        )


def normalize_document_id(path: str) -> str:
    """Normalize a repo-relative or absolute path into a stable document_id."""
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def structural_chunk_key(
    *, section: str | None, chunk_index: int, symbol: str | None = None
) -> str:
    if symbol:
        return f"symbol:{symbol}"
    if section:
        return f"section:{section}|{chunk_index}"
    return f"chunk:{chunk_index}"


def build_chunk_identity(
    *,
    workspace_id: str,
    source_id: str,
    document_path: str,
    chunk_index: int,
    section: str | None = None,
    symbol: str | None = None,
) -> ChunkKey:
    document = DocumentIdentity(
        workspace_id=workspace_id,
        source_id=source_id,
        document_id=normalize_document_id(document_path),
    )
    return ChunkKey(
        document=document,
        chunk_key=structural_chunk_key(section=section, chunk_index=chunk_index, symbol=symbol),
        chunk_index=chunk_index,
    )
