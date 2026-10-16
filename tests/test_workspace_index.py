"""Multi-workspace indexing walks Source roots and stamps identities."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, load_config
from rag.indexer.run import build_chunks, run_index
from rag.indexer.source_model import discover_workspace_files
from rag.store import VectorStore


class FakeEmbedder:
    def __init__(self, *_args, **_kwargs):
        pass

    def health_check(self):
        return True, "ok"

    def embed_texts(self, texts, *, for_query: bool = False):
        return [[float(len(t) % 7), 0.1, 0.2, 0.3] for t in texts]


def _write_manifest(path: Path, workspace_id: str, root: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"id: {workspace_id}",
                f"name: {workspace_id}",
                "roots:",
                "  - id: docs",
                f"    path: {root}",
                "    type: architecture_docs",
                "    include:",
                '      - "**/*.md"',
                "  - id: code",
                f"    path: {root}",
                "    type: source_code",
                "    include:",
                '      - "**/*.py"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_discover_and_chunk_stamp_workspace_and_source(tmp_path: Path):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    (alpha / "docs").mkdir(parents=True)
    (beta / "docs").mkdir(parents=True)
    (alpha / "src").mkdir(parents=True)
    (alpha / "docs" / "a.md").write_text("# Alpha\n\nalpha secret\n", encoding="utf-8")
    (alpha / "src" / "main.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (beta / "docs" / "b.md").write_text("# Beta\n\nbeta secret\n", encoding="utf-8")

    man_a = tmp_path / "alpha.yaml"
    man_b = tmp_path / "beta.yaml"
    _write_manifest(man_a, "alpha", alpha)
    _write_manifest(man_b, "beta", beta)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {man_a}\n"
        f"  - {man_b}\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n"
        "  sources: all\n"
        "qdrant:\n  mode: memory\n  collection: ws\n"
        "embedding:\n  model: fake\n",
        encoding="utf-8",
    )
    config = load_config(config_path)

    alpha_files = discover_workspace_files(config, workspace_id="alpha")
    assert {source for _path, source, _bucket, _identity in alpha_files} == {"docs", "code"}
    assert len(alpha_files) == 2
    assert all(not Path(identity).is_absolute() for _p, _s, _b, identity in alpha_files)

    chunks = build_chunks(config, workspace_id="alpha")
    assert chunks
    assert {c["workspace_id"] for c in chunks} == {"alpha"}
    assert {"docs", "code"} <= {c["source_id"] for c in chunks}

    all_chunks = build_chunks(config)
    assert {"alpha", "beta"} == {c["workspace_id"] for c in all_chunks}


def test_scoped_index_uses_inplace_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from rag.indexer import run as run_mod

    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    (alpha / "docs").mkdir(parents=True)
    (beta / "docs").mkdir(parents=True)
    (alpha / "docs" / "a.md").write_text("# Alpha\n\nalpha only\n", encoding="utf-8")
    (beta / "docs" / "b.md").write_text("# Beta\n\nbeta only\n", encoding="utf-8")

    man_a = tmp_path / "alpha.yaml"
    man_b = tmp_path / "beta.yaml"
    _write_manifest(man_a, "alpha", alpha)
    _write_manifest(man_b, "beta", beta)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {man_a}\n"
        f"  - {man_b}\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n"
        "  sources: all\n"
        "qdrant:\n  mode: memory\n  collection: shared\n"
        "embedding:\n  model: fake\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    monkeypatch.setattr(run_mod, "EmbeddingClient", FakeEmbedder)
    called: dict[str, str] = {}

    def fake_inplace(config, *, embedder, chunks, workspace_id, vector_size):
        called["workspace_id"] = workspace_id
        return {
            "index_mode": "workspace",
            "workspace_id": workspace_id,
            "chunk_count": len(chunks),
            "vector_size": vector_size,
        }

    monkeypatch.setattr(run_mod, "_run_index_workspace_inplace", fake_inplace)
    status = run_index(config, workspace_id="alpha")
    assert called["workspace_id"] == "alpha"
    assert status["index_mode"] == "workspace"


def test_delete_by_workspace_keeps_peer_vectors(tmp_path: Path):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    (alpha / "docs").mkdir(parents=True)
    (beta / "docs").mkdir(parents=True)
    (alpha / "docs" / "a.md").write_text("# Alpha\n\nalpha only\n", encoding="utf-8")
    (beta / "docs" / "b.md").write_text("# Beta\n\nbeta only\n", encoding="utf-8")

    man_a = tmp_path / "alpha.yaml"
    man_b = tmp_path / "beta.yaml"
    _write_manifest(man_a, "alpha", alpha)
    _write_manifest(man_b, "beta", beta)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {man_a}\n"
        f"  - {man_b}\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n"
        "  sources: all\n"
        "qdrant:\n  mode: memory\n  collection: shared\n"
        "embedding:\n  model: fake\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    chunks = build_chunks(config)
    embedder = FakeEmbedder()
    store = VectorStore(config)
    try:
        vectors = embedder.embed_texts([c["content"] for c in chunks], for_query=False)
        store.recreate_collection(len(vectors[0]))
        store.upsert_chunks(chunks, vectors)
        before = store.count()
        store.delete_by_workspace("alpha")
        after = store.count()
        assert after < before
        hits = store.search(
            [1.0, 0.1, 0.2, 0.3],
            top_k=10,
            score_threshold=0.0,
            workspace_id="beta",
        )
        assert hits
        assert all((h.payload or {}).get("workspace_id") == "beta" for h in hits)
    finally:
        store.close()


def test_legacy_build_chunks_still_uses_default_workspace(tmp_path: Path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# Doc\n\nhello\n", encoding="utf-8")
    config = Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="legacy"),
        index=IndexConfig(
            repo_root=str(repo),
            status_file=str(tmp_path / "status.json"),
            knowledge=["docs/**/*.md"],
            code=[],
            sources="knowledge",
        ),
    )
    chunks = build_chunks(config)
    assert chunks
    assert all(c["workspace_id"] == "default" for c in chunks)
    assert all(c["source_id"] == "knowledge" for c in chunks)
