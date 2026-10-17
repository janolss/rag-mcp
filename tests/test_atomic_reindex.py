"""Atomic full-index activation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig
from rag.indexer.collections import CollectionRouter


def test_router_activate_and_rollback(tmp_path: Path):
    config = Config(
        qdrant=QdrantConfig(mode="memory", collection="base"),
        index=IndexConfig(status_file=str(tmp_path / "status.json")),
    )
    router = CollectionRouter(config, state_path=tmp_path / "router.sqlite3")
    assert router.active_collection() == "base"
    router.activate("base__staging_1", vector_size=8)
    assert router.active_collection() == "base__staging_1"
    assert router.previous_collection() == "base"
    assert router.rollback() == "base"
    assert router.active_collection() == "base"


def test_failed_staging_does_not_activate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from rag.indexer import run as run_mod
    from tests.workspace_fixtures import with_workspace_manifest

    config = with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="base"),
            index=IndexConfig(
                repo_root=str(tmp_path),
                status_file=str(tmp_path / "status.json"),
                knowledge=["*.md"],
                code=[],
                sources="knowledge",
            ),
        ),
        tmp_path,
    )
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")

    class Boom:
        def health_check(self):
            return True, "ok"

        def embed_texts(self, texts, *, for_query: bool = False):
            raise RuntimeError("embed failed")

    monkeypatch.setattr(run_mod, "EmbeddingClient", lambda _cfg: Boom())
    router = CollectionRouter(config, state_path=tmp_path / "router.sqlite3")
    monkeypatch.setattr(run_mod, "CollectionRouter", lambda cfg: router)

    with pytest.raises(RuntimeError, match="embed failed"):
        run_mod.run_index(config)
    assert router.active_collection() == "base"
