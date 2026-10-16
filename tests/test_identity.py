"""Stable identity tests."""

from __future__ import annotations

from rag.indexer.identity import build_chunk_identity, content_hash, normalize_document_id


def test_document_id_normalization():
    assert normalize_document_id("./apps/web/a.ts") == "apps/web/a.ts"
    assert normalize_document_id("apps\\web\\a.ts") == "apps/web/a.ts"


def test_chunk_identity_stable_across_content_changes():
    first = build_chunk_identity(
        workspace_id="ws",
        source_id="code",
        document_path="apps/web/a.ts",
        chunk_index=0,
        section=None,
    )
    second = build_chunk_identity(
        workspace_id="ws",
        source_id="code",
        document_path="apps/web/a.ts",
        chunk_index=0,
        section=None,
    )
    assert first.point_id == second.point_id
    assert content_hash("old") != content_hash("new")


def test_same_path_different_workspaces_differ():
    a = build_chunk_identity(
        workspace_id="a",
        source_id="code",
        document_path="src/main.py",
        chunk_index=0,
    )
    b = build_chunk_identity(
        workspace_id="b",
        source_id="code",
        document_path="src/main.py",
        chunk_index=0,
    )
    assert a.point_id != b.point_id
