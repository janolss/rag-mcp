"""Integration smoke: index + filtered search with mocked embeddings."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rag.config import AppRule, Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.embeddings import EmbeddingClient
from rag.indexer.run import build_chunks, build_chunks_for_files
from rag.retrieval.context_pack import get_context_pack
from rag.retrieval.impact import find_gaps, impact_of_change, looks_like_path
from rag.retrieval.search import apply_path_prefix, lexical_score, rerank_hits, search_code, search_knowledge
from rag.retrieval.trace import trace_requirement
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
    (repo / "docs" / "requirements").mkdir(parents=True)
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
    (repo / "docs" / "requirements" / "booking.md").write_text(
        "# Booking\n\nREQ-42 ensures bookings are isolated per tenant.\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Sample workspace\n", encoding="utf-8")
    (repo / "apps" / "web" / "services" / "BookingService.ts").write_text(
        "// REQ-42 tenant booking\nexport class BookingService { book() { return true; } }\n",
        encoding="utf-8",
    )
    (repo / "apps" / "web" / "tests" / "booking.test.ts").write_text(
        "test('book', () => { expect(true).toBe(true); });\n",
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
            sources="all",
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
        search=SearchConfig(top_k=5, score_threshold=0.0, vector_weight=0.7, lexical_weight=0.3),
    )


def test_build_chunks_includes_devdoc(rag_config: Config):
    chunks = build_chunks(rag_config)
    assert chunks
    docs = [c for c in chunks if c["type"] == "documentation"]
    assert docs
    assert all(c["app"] == "global" for c in docs)
    files = {c["file"] for c in chunks}
    assert any(f.startswith(".devdoc/") for f in files)


def test_build_chunks_extracts_requirement_ids_and_lines(rag_config: Config):
    chunks = build_chunks(rag_config)
    req_chunks = [c for c in chunks if "REQ-42" in (c.get("requirement_ids") or [])]
    assert req_chunks
    assert any(c.get("start_line") for c in req_chunks)


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


def test_get_context_pack_and_trace(rag_config: Config):
    embedder = FakeEmbedder()
    chunks = build_chunks(rag_config)
    store = VectorStore(rag_config)
    try:
        vectors = embedder.embed_texts([c["content"] for c in chunks], for_query=False)
        store.recreate_collection(len(vectors[0]))
        store.upsert_chunks(chunks, vectors)

        pack = get_context_pack(
            rag_config,
            "REQ-42 booking tenant",
            app="web",
            store=store,
            embedder=embedder,
        )
        assert "## Documentation" in pack
        assert "## Code" in pack
        assert "## Files to read first" in pack

        traced = trace_requirement(
            rag_config,
            "REQ-42",
            app="web",
            store=store,
            embedder=embedder,
        )
        assert "## Documentation" in traced
        assert "## Code/Tests" in traced
        assert "REQ-42" in traced
    finally:
        store.close()


def test_impact_and_gaps(rag_config: Config):
    embedder = FakeEmbedder()
    chunks = build_chunks(rag_config)
    store = VectorStore(rag_config)
    try:
        vectors = embedder.embed_texts([c["content"] for c in chunks], for_query=False)
        store.recreate_collection(len(vectors[0]))
        store.upsert_chunks(chunks, vectors)

        impact = impact_of_change(
            rag_config,
            "apps/web/services/BookingService.ts",
            app="web",
            store=store,
            embedder=embedder,
        )
        assert "## Likely affected code" in impact
        assert "## Related requirements/docs" in impact

        gaps = find_gaps(
            rag_config,
            "booking",
            app="web",
            store=store,
            embedder=embedder,
        )
        assert "## Documentation without clear code" in gaps
        assert "heuristic" in gaps.lower()
    finally:
        store.close()


def test_path_prefix_filter_and_rerank():
    assert looks_like_path("apps/web/services/BookingService.ts")
    assert not looks_like_path("add a new booking flow with tests")

    class Hit:
        def __init__(self, file: str, content: str, score: float):
            self.payload = {"file": file, "content": content}
            self.score = score

    hits = [
        Hit("docs/a.md", "alpha", 0.9),
        Hit("apps/web/x.ts", "booking service", 0.5),
    ]
    filtered = apply_path_prefix(hits, "apps/web/")
    assert len(filtered) == 1
    assert filtered[0].payload["file"] == "apps/web/x.ts"

    assert lexical_score("booking service", hits[1].payload) > 0.5
    ranked = rerank_hits(hits, "booking service", vector_weight=0.5, lexical_weight=0.5, top_k=2)
    assert ranked[0].payload["file"] == "apps/web/x.ts"


def test_build_chunks_for_files(rag_config: Config):
    chunks = build_chunks_for_files(rag_config, ["apps/web/services/BookingService.ts"])
    assert chunks
    assert all(c["file"].endswith("BookingService.ts") for c in chunks)
