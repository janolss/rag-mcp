"""Cross-cutting multi-workspace acceptance tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.domain.models import Relationship, Source, Workspace
from rag.relationships.registry import RelationshipRegistry
from rag.security.access import AccessDenied, Principal, authorize_workspace
from rag.services import ServiceApp, WorkspaceRequiredError
from rag.store import VectorStore
from rag.workspaces.registry import WorkspaceRegistry


def _config(tmp_path: Path) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="accept"),
        index=IndexConfig(
            repo_root=str(tmp_path),
            status_file=str(tmp_path / "status.json"),
            knowledge=[],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )


def test_acceptance_isolation_and_related_acl(tmp_path: Path):
    registry = WorkspaceRegistry(
        [
            Workspace(
                id="alpha",
                name="Alpha",
                sources=(Source(id="knowledge", type="docs", root="."),),
                relationships=(Relationship(target="beta", type="depends_on"),),
            ),
            Workspace(
                id="beta",
                name="Beta",
                sources=(Source(id="knowledge", type="docs", root="."),),
            ),
            Workspace(id="gamma", name="Gamma"),
        ]
    )
    rel = RelationshipRegistry.from_workspace_registry(registry)
    principal = Principal(subject="u", workspace_allowlist=frozenset({"alpha", "beta"}))
    ids = rel.related_workspace_ids("alpha", principal=principal)
    assert ids == ["alpha", "beta"]
    assert "gamma" not in ids
    authorize_workspace(principal, "alpha")
    with pytest.raises(AccessDenied):
        authorize_workspace(principal, "gamma")


def test_acceptance_multi_workspace_requires_id(tmp_path: Path, monkeypatch):
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

    monkeypatch.setattr("rag.services.resolve.WorkspaceRegistry", FakeRegistry)
    app = ServiceApp(config)
    with pytest.raises(WorkspaceRequiredError):
        app.sources.list_sources()
    assert app.workspaces.list_workspaces()


def test_acceptance_store_workspace_filter(tmp_path: Path):
    store = VectorStore(_config(tmp_path))
    try:
        store.ensure_collection(4)
        chunk_a = {
            "type": "documentation",
            "app": "shared",
            "file": "a.md",
            "language": "markdown",
            "section": None,
            "chunk_index": 0,
            "content": "alpha secret",
            "requirement_ids": [],
            "workspace_id": "alpha",
            "source_id": "knowledge",
            "revision": 1,
        }
        chunk_b = dict(chunk_a, file="b.md", content="beta secret", workspace_id="beta")
        store.upsert_chunks([chunk_a, chunk_b], [[0.1, 0.2, 0.3, 0.4], [0.1, 0.2, 0.3, 0.4]])
        hits = store.search(
            [0.1, 0.2, 0.3, 0.4],
            top_k=10,
            score_threshold=None,
            workspace_id="alpha",
        )
        files = {(h.payload or {}).get("file") for h in hits}
        assert "a.md" in files
        assert "b.md" not in files
    finally:
        store.close()
