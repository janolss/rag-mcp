"""Index compatibility manifest for schema/model/dimension/chunker versions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rag.indexer.identity import PAYLOAD_SCHEMA_VERSION

CHUNKER_VERSION = 1
INDEXING_VERSION = 1


class IndexCompatibilityError(RuntimeError):
    """Raised when an existing index is incompatible with current config."""


@dataclass(frozen=True)
class IndexManifest:
    payload_schema_version: int
    chunker_version: int
    indexing_version: int
    embedding_model: str
    vector_size: int
    collection: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexManifest:
        return cls(
            payload_schema_version=int(data.get("payload_schema_version") or 0),
            chunker_version=int(data.get("chunker_version") or 0),
            indexing_version=int(data.get("indexing_version") or 0),
            embedding_model=str(data.get("embedding_model") or ""),
            vector_size=int(data.get("vector_size") or 0),
            collection=str(data.get("collection") or ""),
        )


def current_manifest(
    *,
    embedding_model: str,
    vector_size: int,
    collection: str,
) -> IndexManifest:
    return IndexManifest(
        payload_schema_version=PAYLOAD_SCHEMA_VERSION,
        chunker_version=CHUNKER_VERSION,
        indexing_version=INDEXING_VERSION,
        embedding_model=embedding_model,
        vector_size=vector_size,
        collection=collection,
    )


def write_manifest(path: Path, manifest: IndexManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> IndexManifest | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return IndexManifest.from_dict(data)


def check_compatibility(
    existing: IndexManifest | None,
    expected: IndexManifest,
    *,
    allow_missing: bool = True,
) -> None:
    if existing is None:
        if allow_missing:
            return
        raise IndexCompatibilityError("index manifest is missing")
    if existing.payload_schema_version == 0:
        raise IndexCompatibilityError(
            "legacy index (schema v0) is read-only; run a full reindex to migrate"
        )
    mismatches: list[str] = []
    if existing.payload_schema_version != expected.payload_schema_version:
        mismatches.append("payload_schema_version")
    if existing.chunker_version != expected.chunker_version:
        mismatches.append("chunker_version")
    if existing.indexing_version != expected.indexing_version:
        mismatches.append("indexing_version")
    if existing.embedding_model != expected.embedding_model:
        mismatches.append("embedding_model")
    if (
        existing.vector_size
        and expected.vector_size
        and existing.vector_size != expected.vector_size
    ):
        mismatches.append("vector_size")
    if mismatches:
        raise IndexCompatibilityError(
            "incompatible index manifest fields: " + ", ".join(mismatches)
        )
