"""Document registry tests."""

from __future__ import annotations

from pathlib import Path

from rag.indexer.document_registry import DocumentRegistry


def test_registry_upsert_get_and_delete(tmp_path: Path):
    registry = DocumentRegistry(tmp_path / "reg.sqlite3")
    registry.upsert(
        workspace_id="default",
        source_id="code",
        document_id="a.py",
        content_hash="abc",
        revision=1,
        status="active",
        path="a.py",
    )
    loaded = registry.get("default", "code", "a.py")
    assert loaded is not None
    assert loaded.content_hash == "abc"
    registry.mark_deleted(workspace_id="default", source_id="code", document_id="a.py")
    assert registry.list_workspace("default") == []
