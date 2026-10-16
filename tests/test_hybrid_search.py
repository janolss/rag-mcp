"""Keyword and hybrid RRF search tests (Phase 9)."""

from __future__ import annotations

from pathlib import Path

from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.retrieval.fusion import reciprocal_rank_fusion
from rag.retrieval.lexical import LexicalIndex
from rag.services.search import SearchServiceImpl


def test_rrf_fuses_two_lists():
    class Item:
        def __init__(self, point_id: str):
            self.point_id = point_id

    fused = reciprocal_rank_fusion(
        [[Item("a"), Item("b")], [Item("b"), Item("c")]],
        id_fn=lambda x: x.point_id,
        k=60,
        limit=3,
    )
    ids = [row[0] for row in fused]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}


def test_keyword_finds_exact_token(tmp_path: Path):
    index = LexicalIndex(tmp_path / "lex.sqlite3")
    index.upsert_documents(
        [
            {
                "point_id": "1",
                "workspace_id": "default",
                "source_id": "knowledge",
                "document_id": "a.md",
                "file": "a.md",
                "content": "The booking-xyzzy requirement is unique.",
            },
            {
                "point_id": "2",
                "workspace_id": "default",
                "source_id": "knowledge",
                "document_id": "b.md",
                "file": "b.md",
                "content": "Unrelated authentication notes.",
            },
        ]
    )
    hits = index.search("booking-xyzzy", workspace_id="default", limit=5)
    assert hits
    assert hits[0].point_id == "1"


def test_hybrid_service_mode(tmp_path: Path, monkeypatch):
    config = Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="hyb"),
        index=IndexConfig(
            repo_root=str(tmp_path),
            status_file=str(tmp_path / "status.json"),
            knowledge=[],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0, rrf_k=60),
    )
    lexical = LexicalIndex(tmp_path / "lex.sqlite3")
    lexical.upsert_documents(
        [
            {
                "point_id": "p1",
                "workspace_id": "default",
                "source_id": "knowledge",
                "document_id": "rare.md",
                "file": "rare.md",
                "content": "token-unique-42 appears only here",
            }
        ]
    )

    class FakeHit:
        def __init__(self):
            self.score = 0.1
            self.payload = {
                "point_id": "p2",
                "workspace_id": "default",
                "file": "other.md",
                "content": "vector neighbor",
            }

    monkeypatch.setattr(
        "rag.retrieval.search.search_hits",
        lambda *args, **kwargs: [FakeHit()],
    )
    service = SearchServiceImpl(config, lexical=lexical)
    keyword = service.search(query="token-unique-42", search_mode="keyword")
    assert keyword and keyword[0]["file"] == "rare.md"

    hybrid = service.search(query="token-unique-42", search_mode="hybrid")
    assert hybrid
    files = {h["file"] for h in hybrid}
    assert "rare.md" in files
