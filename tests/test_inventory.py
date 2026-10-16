"""Inventory classification tests."""

from __future__ import annotations

from pathlib import Path

from rag.indexer.document_registry import DocumentRegistry
from rag.indexer.identity import content_hash
from rag.indexer.inventory import ObservedDocument, classify_inventory


def test_inventory_new_changed_unchanged_deleted(tmp_path: Path):
    registry = DocumentRegistry(tmp_path / "reg.sqlite3")
    registry.upsert(
        workspace_id="default",
        source_id="knowledge",
        document_id="keep.md",
        content_hash=content_hash("same"),
        revision=1,
        status="active",
        path="keep.md",
    )
    registry.upsert(
        workspace_id="default",
        source_id="knowledge",
        document_id="changed.md",
        content_hash=content_hash("older"),
        revision=1,
        status="active",
        path="changed.md",
    )
    registry.upsert(
        workspace_id="default",
        source_id="knowledge",
        document_id="gone.md",
        content_hash="x",
        revision=1,
        status="active",
        path="gone.md",
    )
    observed = [
        ObservedDocument("default", "knowledge", "keep.md", "keep.md", content_hash("same")),
        ObservedDocument("default", "knowledge", "changed.md", "changed.md", content_hash("new")),
    ]
    diff = classify_inventory(registry, observed, workspace_id="default")
    assert [item.document_id for item in diff.new] == []
    assert [item.document_id for item, _ in diff.unchanged] == ["keep.md"]
    assert [item.document_id for item, _ in diff.changed] == ["changed.md"]
    assert [item.document_id for item in diff.deleted] == ["gone.md"]
