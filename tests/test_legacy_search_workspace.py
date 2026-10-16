"""Legacy search tools resolve a single non-default workspace."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, load_config
from rag.embeddings import EmbeddingClient
from rag.mcp_server import create_mcp_server
from rag.retrieval.search import search_hits, search_knowledge
from rag.runtime import RagRuntime
from rag.store import VectorStore


class FakeEmbedder(EmbeddingClient):
    def __init__(self):
        self._config = EmbeddingConfig(model="fake-model", batch_size=8)
        self._url = "http://fake/v1/embeddings"
        self._timeout = 1.0

    def embed_texts(self, texts, *, for_query: bool = False):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def health_check(self):
        return True, "ok"


def _single_manifest_config(tmp_path: Path) -> Config:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "readme.md").write_text("# hi\n", encoding="utf-8")
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "id: lk_apps",
                "name: Example Apps",
                "roots:",
                "  - id: docs",
                f"    path: {root}",
                "    type: architecture_docs",
                "    include:",
                '      - "**/*.md"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {manifest}\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n"
        "  sources: knowledge\n"
        "  knowledge: []\n"
        "  code: []\n"
        "qdrant:\n  mode: memory\n  collection: legacy_ws\n"
        "embedding:\n  model: fake\n"
        "mcp:\n  capabilities:\n    knowledge: true\n    code: true\n    lis: false\n",
        encoding="utf-8",
    )
    return load_config(config_path)


def test_search_hits_auto_resolves_single_manifest_workspace(tmp_path: Path):
    config = _single_manifest_config(tmp_path)
    store = VectorStore(config)
    embedder = FakeEmbedder()
    try:
        store.ensure_collection(4)
        store.upsert_chunks(
            [
                {
                    "type": "documentation",
                    "app": "global",
                    "file": "readme.md",
                    "language": "markdown",
                    "section": None,
                    "chunk_index": 0,
                    "content": "tenant isolation notes",
                    "requirement_ids": [],
                    "workspace_id": "lk_apps",
                    "source_id": "docs",
                }
            ],
            [[0.1, 0.2, 0.3, 0.4]],
        )
        hits = search_hits(
            config,
            "tenant isolation",
            type_filter=["documentation"],
            store=store,
            embedder=embedder,
        )
        assert hits
        assert all((h.payload or {}).get("workspace_id") == "lk_apps" for h in hits)

        text = search_knowledge(
            config,
            "tenant isolation",
            store=store,
            embedder=embedder,
        )
        assert "No relevant results found" not in text
    finally:
        store.close()


def test_search_hits_still_requires_id_with_two_workspaces(tmp_path: Path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    for path, wid in ((a, "alpha"), (b, "beta")):
        root = tmp_path / wid
        root.mkdir()
        path.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    f"id: {wid}",
                    f"name: {wid}",
                    "roots:",
                    "  - id: docs",
                    f"    path: {root}",
                    "    type: architecture_docs",
                    "    include:",
                    '      - "**/*.md"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {a}\n"
        f"  - {b}\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n"
        "qdrant:\n  mode: memory\n  collection: multi\n"
        "embedding:\n  model: fake\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    with pytest.raises(ValueError, match="workspace_id is required"):
        search_hits(
            config,
            "query",
            type_filter=["documentation"],
            store=VectorStore(config),
            embedder=FakeEmbedder(),
        )


def test_mcp_legacy_search_tools_expose_workspace_id(tmp_path: Path):
    config = _single_manifest_config(tmp_path)
    runtime = RagRuntime(config)
    runtime._embedder = FakeEmbedder()
    runtime.get_store().ensure_collection(4)
    server = create_mcp_server(config, runtime)

    async def inspect():
        tools = await server.list_tools()
        by_name = {tool.name: tool for tool in tools}
        for name in ("search_knowledge", "search_code"):
            schema = by_name[name].input_schema
            props = schema.get("properties") or {}
            assert "workspace_id" in props
        # Single manifest workspace: omit workspace_id (auto-resolve).
        omitted = await server.call_tool(
            "search_knowledge",
            {"query": "unlikely-token-xyz"},
        )
        explicit = await server.call_tool(
            "search_knowledge",
            {"query": "unlikely-token-xyz", "workspace_id": "lk_apps"},
        )
        return omitted, explicit

    omitted, explicit = asyncio.run(inspect())
    assert omitted.is_error is False
    assert explicit.is_error is False
    assert "No relevant results found" in omitted.content[0].text
