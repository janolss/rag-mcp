"""Integration smoke: index + filtered search with mocked embeddings."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rag.config import AppRule, Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.embeddings import EmbeddingClient
from rag.indexer.run import build_chunks
from rag.retrieval.search import search_code, search_knowledge
from rag.store import VectorStore


def _fake_vector(text: str, dim: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [(digest[i % len(digest)] / 255.0) for i in range(dim)]
    # L2-normalize for cosine
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / norm for v in vals]


class FakeEmbedder(EmbeddingClient):
    def __init__(self):
        # Bypass real HTTP client init
        self._config = EmbeddingConfig(model="fake-model", batch_size=8)
        self._url = "http://fake/v1/embeddings"
        self._timeout = 1.0

    def embed_texts(self, texts, *, for_query: bool = False):
        return [_fake_vector(("q:" if for_query else "d:") + t) for t in texts]

    def health_check(self):
        return True, "ok dim=32 model=fake-model"


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Self-contained workspace fixture (no dependency on an external monorepo)."""
    repo = tmp_path / "workspace"
    (repo / ".devdoc" / "architecture").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "apps" / "web" / "services").mkdir(parents=True)
    (repo / "apps" / "web" / "tests").mkdir(parents=True)

    (repo / ".devdoc" / "architecture" / "multi-tenancy.md").write_text(
        "# Multi-tenancy\n\nTenant isolation uses mysql schemas per customer.\n",
        encoding="utf-8",
    )
    (repo / ".devdoc" / "architecture" / "database-access.md").write_text(
        "# Database access\n\nPrefer repository patterns for mysql access.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "onboarding.md").write_text(
        "# Onboarding\n\nStart with multi-tenancy docs.\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Sample workspace\n", encoding="utf-8")
    (repo / "apps" / "web" / "services" / "BookingService.ts").write_text(
        "export class BookingService { book() { return true; } }\n",
        encoding="utf-8",
    )
    return repo


@pytest.fixture()
def rag_config(tmp_path: Path, sample_repo: Path) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake-model"),
        qdrant=QdrantConfig(mode="memory", collection="test_workspace_rag"),
        index=IndexConfig(
            repo_root=str(sample_repo),
            sources="knowledge",
            chunk_size=800,
            chunk_overlap=80,
            status_file=str(tmp_path / "status.json"),
            knowledge=[
                "README.md",
                "docs/**/*.md",
                ".devdoc/**/*.md",
            ],
            code=[
                "apps/**/*.ts",
                "apps/**/*.js",
            ],
            apps=[
                AppRule(prefix="apps/web/", name="web"),
            ],
            documentation_prefixes=[".devdoc/", "docs/"],
        ),
        search=SearchConfig(top_k=5, score_threshold=0.0),
    )


def test_build_chunks_includes_devdoc(rag_config: Config):
    chunks = build_chunks(rag_config)
    assert chunks
    assert all(c["type"] == "documentation" for c in chunks)
    assert all(c["app"] == "global" for c in chunks)
    files = {c["file"] for c in chunks}
    assert any(f.startswith(".devdoc/") for f in files)


def test_index_and_search_roundtrip(rag_config: Config):
    embedder = FakeEmbedder()
    chunks = build_chunks(rag_config)
    focused = [c for c in chunks if "multi-tenancy" in c["file"] or "database-access" in c["file"]]
    assert focused, "expected multi-tenancy / database-access docs in fixtures"

    store = VectorStore(rag_config)
    try:
        vectors = embedder.embed_texts([c["content"] for c in focused], for_query=False)
        store.recreate_collection(len(vectors[0]))
        store.upsert_chunks(focused, vectors)

        result = search_knowledge(
            rag_config,
            "tenant isolation mysql",
            store=store,
            embedder=embedder,
        )
        assert "No relevant results found." not in result
        assert ".devdoc/" in result

        # Code search against a docs-only index should return nothing useful
        code_result = search_code(
            rag_config,
            "tenant isolation mysql",
            app="web",
            store=store,
            embedder=embedder,
        )
        assert code_result == "No relevant results found."
    finally:
        store.close()


def test_search_code_rejects_unknown_app(rag_config: Config):
    result = search_code(rag_config, "anything", app="unknown-app")
    assert result.startswith("Error: app must be one of")
