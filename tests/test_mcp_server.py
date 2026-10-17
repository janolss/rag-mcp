import asyncio
import hashlib
import json
from pathlib import Path

from pydantic import AnyUrl
from rag.config import (
    CapabilitiesConfig,
    Config,
    EmbeddingConfig,
    IndexConfig,
    McpConfig,
    QdrantConfig,
)
from rag.embeddings import EmbeddingClient
from rag.mcp_server import create_mcp_server
from rag.runtime import RagRuntime
from rag.version import package_version
from tests.workspace_fixtures import with_workspace_manifest


def _fake_vector(text: str, dim: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [(digest[i % len(digest)] / 255.0) for i in range(dim)]
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / norm for v in vals]


class FakeEmbedder(EmbeddingClient):
    def __init__(self):
        self._config = EmbeddingConfig(model="fake-model", batch_size=8)
        self._url = "http://fake/v1/embeddings"
        self._timeout = 1.0

    def embed_texts(self, texts, *, for_query: bool = False):
        return [_fake_vector(("q:" if for_query else "d:") + t) for t in texts]

    def health_check(self):
        return True, "ok dim=32 model=fake-model"


def _make(tmp_path: Path, knowledge=True, code=True, lis=False):
    config = with_workspace_manifest(
        Config(
            qdrant=QdrantConfig(mode="memory", collection="mcp_reg"),
            index=IndexConfig(repo_root=str(tmp_path), sources="all"),
            mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=knowledge, code=code, lis=lis)),
        ),
        tmp_path,
    )
    runtime = RagRuntime(config)
    runtime._embedder = FakeEmbedder()
    server = create_mcp_server(config, runtime)
    return server, config, runtime


def test_mcp_server_registers_tools_resources_and_prompts(tmp_path: Path):
    server, _, _ = _make(tmp_path, knowledge=True, code=True, lis=False)

    async def list_registrations():
        return (
            await server.list_tools(),
            await server.list_resources(),
            await server.list_prompts(),
        )

    tools, resources, prompts = asyncio.run(list_registrations())

    names = {tool.name for tool in tools}
    assert "search_knowledge" in names
    assert "search_code" in names
    assert "search_lis" not in names
    assert "rag://status" in {str(resource.uri) for resource in resources}
    assert "change-plan" in {prompt.name for prompt in prompts}


def test_mcp_server_metadata_includes_version(tmp_path: Path):
    server, _, _ = _make(tmp_path)
    assert server.version == package_version()
    assert server.title == "Workspace RAG"
    assert server.description


def test_mcp_tool_validation_is_error(tmp_path: Path):
    server, _, _ = _make(tmp_path, knowledge=True, code=False, lis=False)

    async def call_empty():
        return await server.call_tool("search_knowledge", {"query": ""})

    result = asyncio.run(call_empty())
    assert result.is_error is True
    assert "cannot be empty" in result.content[0].text


def test_mcp_tool_empty_results_are_not_errors(tmp_path: Path):
    server, _, runtime = _make(tmp_path, knowledge=True, code=False, lis=False)
    runtime.get_store().ensure_collection(32)

    async def call_query():
        return await server.call_tool(
            "search_knowledge",
            {"query": "unlikely-token-xyz-12345"},
        )

    result = asyncio.run(call_query())
    assert result.is_error is False
    assert "No relevant results found" in result.content[0].text


def test_mcp_resources_always_json(tmp_path: Path):
    server, _, _ = _make(tmp_path)

    async def read_both():
        status = await server.read_resource(AnyUrl("rag://status"))
        sources = await server.read_resource(AnyUrl("rag://sources"))
        return status, sources

    status, sources = asyncio.run(read_both())

    def _text(resource_result) -> str:
        if isinstance(resource_result, str):
            return resource_result
        if isinstance(resource_result, list) and resource_result:
            first = resource_result[0]
            return getattr(first, "content", None) or getattr(first, "text", None) or str(first)
        contents = getattr(resource_result, "contents", None)
        if contents:
            first = contents[0]
            return getattr(first, "content", None) or getattr(first, "text", None) or str(first)
        return str(resource_result)

    status_payload = json.loads(_text(status))
    sources_payload = json.loads(_text(sources))
    assert "ok" in status_payload
    assert sources_payload["ok"] is True
    assert "workspaces" in sources_payload
