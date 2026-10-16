"""Versioned payload schema tests."""

from __future__ import annotations

from rag.indexer.payload import PAYLOAD_SCHEMA_VERSION, build_payload, is_legacy_payload


def test_build_payload_separates_hash_from_identity():
    chunk = {
        "type": "code",
        "app": "web",
        "file": "apps/web/a.ts",
        "language": "typescript",
        "section": None,
        "chunk_index": 0,
        "content": "export const x = 1",
        "requirement_ids": [],
        "start_line": 1,
        "end_line": 1,
    }
    first = build_payload(chunk, workspace_id="ws", source_id="code", revision=1)
    chunk["content"] = "export const x = 2"
    second = build_payload(chunk, workspace_id="ws", source_id="code", revision=2)
    assert first["point_id"] == second["point_id"]
    assert first["content_hash"] != second["content_hash"]
    assert first["schema_version"] == PAYLOAD_SCHEMA_VERSION
    assert first["document_id"] == "apps/web/a.ts"
    assert first["workspace_id"] == "ws"
    assert first["source_id"] == "code"


def test_legacy_payload_detection():
    assert is_legacy_payload({"file": "a.py"})
    assert not is_legacy_payload({"schema_version": PAYLOAD_SCHEMA_VERSION})
