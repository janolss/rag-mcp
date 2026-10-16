"""Incremental indexing behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.indexer.document_registry import DocumentRegistry
from rag.indexer.incremental import IncrementalIndexError, registry_path_for, run_incremental


class FakeEmbedder:
    def __init__(self, *_args, **_kwargs):
        self.calls = 0

    def health_check(self):
        return True, "ok"

    def embed_texts(self, texts, *, for_query: bool = False):
        self.calls += 1
        return [[float(len(t) % 7), 0.1, 0.2, 0.3] for t in texts]


class BoomEmbedder(FakeEmbedder):
    def embed_texts(self, texts, *, for_query: bool = False):
        raise RuntimeError("embed failed")


def _config(tmp_path: Path, repo: Path) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="inc"),
        index=IndexConfig(
            repo_root=str(repo),
            status_file=str(tmp_path / "status.json"),
            knowledge=["docs/**/*.md"],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )


def test_unchanged_files_skip_reembed(tmp_path: Path, monkeypatch):
    from rag.indexer import incremental as inc

    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# A\n\nhello\n", encoding="utf-8")
    config = _config(tmp_path, repo)
    monkeypatch.setattr(inc, "EmbeddingClient", FakeEmbedder)
    first = run_incremental(config)
    assert first["new"] == 1
    second = run_incremental(config)
    assert second["unchanged"] == 1
    assert second["new"] == 0
    assert second["upserted_chunks"] == 0


def test_deleted_file_retired_after_inventory(tmp_path: Path, monkeypatch):
    from rag.indexer import incremental as inc

    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    target = docs / "a.md"
    target.write_text("# A\n\nhello\n", encoding="utf-8")
    config = _config(tmp_path, repo)
    monkeypatch.setattr(inc, "EmbeddingClient", FakeEmbedder)
    run_incremental(config)
    target.unlink()
    stats = run_incremental(config)
    assert stats["deleted"] == 1
    registry = DocumentRegistry(registry_path_for(config))
    assert registry.list_workspace("default") == []


def test_failed_write_keeps_previous_registry(tmp_path: Path, monkeypatch):
    from rag.indexer import incremental as inc

    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    target = docs / "a.md"
    target.write_text("# A\n\nhello\n", encoding="utf-8")
    config = _config(tmp_path, repo)
    monkeypatch.setattr(inc, "EmbeddingClient", FakeEmbedder)
    run_incremental(config)
    registry = DocumentRegistry(registry_path_for(config))
    before = registry.get("default", "knowledge", "docs/a.md")
    assert before is not None
    assert before.status == "active"

    target.write_text("# A\n\nchanged\n", encoding="utf-8")
    monkeypatch.setattr(inc, "EmbeddingClient", BoomEmbedder)
    with pytest.raises(RuntimeError, match="embed failed"):
        run_incremental(config)

    after = registry.get("default", "knowledge", "docs/a.md")
    assert after is not None
    assert after.status == "active"
    assert after.content_hash == before.content_hash
    assert after.revision == before.revision


def test_idempotent_rerun_is_stable(tmp_path: Path, monkeypatch):
    from rag.indexer import incremental as inc

    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# A\n\nhello\n", encoding="utf-8")
    config = _config(tmp_path, repo)
    monkeypatch.setattr(inc, "EmbeddingClient", FakeEmbedder)
    run_incremental(config)
    third = run_incremental(config)
    fourth = run_incremental(config)
    assert third["unchanged"] == 1
    assert fourth["unchanged"] == 1
    assert third["upserted_chunks"] == 0
    assert fourth["upserted_chunks"] == 0


# Keep error symbol imported for resume/failure assertions in this module.
assert IncrementalIndexError is not None
