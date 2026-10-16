"""Index manifest compatibility tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.indexer.index_manifest import (
    IndexCompatibilityError,
    check_compatibility,
    current_manifest,
    read_manifest,
    write_manifest,
)


def test_write_read_and_compatible(tmp_path: Path):
    manifest = current_manifest(
        embedding_model="m",
        vector_size=32,
        collection="c",
    )
    path = tmp_path / "index_manifest.json"
    write_manifest(path, manifest)
    loaded = read_manifest(path)
    assert loaded == manifest
    check_compatibility(loaded, manifest)


def test_rejects_model_and_legacy_mismatch(tmp_path: Path):
    expected = current_manifest(embedding_model="new", vector_size=32, collection="c")
    existing = current_manifest(embedding_model="old", vector_size=32, collection="c")
    with pytest.raises(IndexCompatibilityError, match="embedding_model"):
        check_compatibility(existing, expected)

    legacy = current_manifest(embedding_model="new", vector_size=32, collection="c")
    object.__setattr__(legacy, "payload_schema_version", 0)  # type: ignore[misc]
    # frozen dataclass - rebuild instead
    from rag.indexer.index_manifest import IndexManifest

    legacy = IndexManifest(
        payload_schema_version=0,
        chunker_version=1,
        indexing_version=1,
        embedding_model="new",
        vector_size=32,
        collection="c",
    )
    with pytest.raises(IndexCompatibilityError, match="legacy"):
        check_compatibility(legacy, expected)
