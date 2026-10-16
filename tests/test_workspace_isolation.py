"""Workspace isolation and search scope tests (Phase 10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from qdrant_client import models
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.store import (
    ScopeDisabledError,
    VectorStore,
    WorkspaceFilterError,
    build_type_app_filter,
)


def _config(tmp_path: Path, collection: str = "iso") -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection=collection),
        index=IndexConfig(
            repo_root=str(tmp_path),
            status_file=str(tmp_path / "status.json"),
            knowledge=[],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )


def _upsert_doc(
    store: VectorStore,
    *,
    workspace_id: str,
    source_id: str,
    document_id: str,
    content: str,
    language: str = "markdown",
) -> None:
    chunk = {
        "type": "documentation",
        "app": "shared",
        "file": document_id,
        "language": language,
        "section": None,
        "chunk_index": 0,
        "content": content,
        "requirement_ids": [],
        "workspace_id": workspace_id,
        "source_id": source_id,
        "revision": 1,
    }
    store.ensure_collection(4)
    store.upsert_chunks([chunk], [[0.1, 0.2, 0.3, 0.4]])


def test_search_requires_workspace_id(tmp_path: Path):
    store = VectorStore(_config(tmp_path))
    try:
        store.ensure_collection(4)
        with pytest.raises(WorkspaceFilterError, match="workspace_id is required"):
            store.search([0.1, 0.2, 0.3, 0.4], top_k=3, score_threshold=None)
    finally:
        store.close()


def test_cross_workspace_isolation(tmp_path: Path):
    store = VectorStore(_config(tmp_path, collection="iso_cross"))
    try:
        _upsert_doc(
            store,
            workspace_id="alpha",
            source_id="knowledge",
            document_id="a.md",
            content="alpha only secret",
        )
        _upsert_doc(
            store,
            workspace_id="beta",
            source_id="knowledge",
            document_id="b.md",
            content="beta only secret",
        )
        hits = store.search(
            [0.1, 0.2, 0.3, 0.4],
            top_k=10,
            score_threshold=None,
            workspace_id="alpha",
        )
        files = {(h.payload or {}).get("file") for h in hits}
        assert "a.md" in files
        assert "b.md" not in files
        workspaces = {(h.payload or {}).get("workspace_id") for h in hits}
        assert workspaces == {"alpha"}
    finally:
        store.close()


def test_source_document_language_filters(tmp_path: Path):
    store = VectorStore(_config(tmp_path, collection="iso_filters"))
    try:
        _upsert_doc(
            store,
            workspace_id="ws",
            source_id="code",
            document_id="apps/a.ts",
            content="typescript service",
            language="typescript",
        )
        _upsert_doc(
            store,
            workspace_id="ws",
            source_id="knowledge",
            document_id="docs/a.md",
            content="markdown guide",
            language="markdown",
        )
        hits = store.search(
            [0.1, 0.2, 0.3, 0.4],
            top_k=10,
            score_threshold=None,
            workspace_id="ws",
            scope="source",
            source_id="code",
            language="typescript",
        )
        assert len(hits) == 1
        assert (hits[0].payload or {}).get("document_id") == "apps/a.ts"

        hits_doc = store.search(
            [0.1, 0.2, 0.3, 0.4],
            top_k=10,
            score_threshold=None,
            workspace_id="ws",
            document_id="docs/a.md",
        )
        assert len(hits_doc) == 1
        assert (hits_doc[0].payload or {}).get("source_id") == "knowledge"
    finally:
        store.close()


def test_related_and_global_scopes_disabled():
    with pytest.raises(ScopeDisabledError, match="related"):
        build_type_app_filter(workspace_id="ws", scope="related")
    with pytest.raises(ScopeDisabledError, match="global"):
        build_type_app_filter(workspace_id="ws", scope="global")


def test_multi_workspace_search_hits_requires_workspace(tmp_path: Path, monkeypatch):
    from rag.domain.models import Workspace
    from rag.retrieval import search as search_mod
    from rag.workspaces.registry import WorkspaceRegistry

    config = _config(tmp_path)

    class FakeRegistry(WorkspaceRegistry):
        @classmethod
        def from_config(cls, _config):
            return cls(
                [
                    Workspace(id="one", name="One"),
                    Workspace(id="two", name="Two"),
                ]
            )

    monkeypatch.setattr(search_mod, "WorkspaceRegistry", FakeRegistry)

    class FakeStore:
        def search(self, *args, **kwargs):
            raise AssertionError("search must not run without workspace")

        def close(self):
            return None

    class FakeEmbedder:
        def embed_query(self, query: str):
            return [0.1, 0.2, 0.3, 0.4]

    with pytest.raises(ValueError, match="workspace_id is required"):
        search_mod.search_hits(
            config,
            "hello",
            type_filter=["documentation"],
            store=FakeStore(),  # type: ignore[arg-type]
            embedder=FakeEmbedder(),  # type: ignore[arg-type]
        )


def test_filter_combines_workspace_and_type():
    filt = build_type_app_filter(
        workspace_id="ws",
        type_filter=["code"],
        source_id="code",
    )
    assert isinstance(filt, models.Filter)
    keys = {c.key for c in filt.must}
    assert keys == {"workspace_id", "type", "source_id"}
