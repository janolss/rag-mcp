"""MCP workspace-aware tool registration and schema tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rag.config import (
    CapabilitiesConfig,
    Config,
    EmbeddingConfig,
    IndexConfig,
    McpConfig,
    QdrantConfig,
)
from rag.mcp_server import create_mcp_server
from rag.runtime import RagRuntime
from tests.workspace_fixtures import with_workspace_manifest


def _make(tmp_path: Path):
    config = with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="mcp_ws"),
            index=IndexConfig(repo_root=str(tmp_path), sources="knowledge"),
            mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=True, code=False, lis=False)),
        ),
        tmp_path,
    )
    runtime = RagRuntime(config)
    server = create_mcp_server(config, runtime)
    return server


def test_workspace_tools_registered(tmp_path: Path):
    server = _make(tmp_path)

    async def list_tools():
        return await server.list_tools()

    tools = asyncio.run(list_tools())
    names = {tool.name for tool in tools}
    assert "list_workspaces" in names
    assert "resolve_workspace" in names
    assert "get_workspace_info" in names
    assert "get_document" in names
    assert "get_index_status" in names
    assert "search" in names
    assert "search_knowledge" in names
    assert "index_status" not in names
    assert "list_sources" in names


def test_list_workspaces_tool_returns_default(tmp_path: Path):
    server = _make(tmp_path)

    async def call():
        return await server.call_tool("list_workspaces", {})

    result = asyncio.run(call())
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload[0]["id"] == "default"


def test_get_workspace_info_unknown_is_error(tmp_path: Path):
    server = _make(tmp_path)

    async def call():
        return await server.call_tool("get_workspace_info", {"workspace_id": "missing"})

    result = asyncio.run(call())
    assert result.is_error is True
    assert (
        "not found" in result.content[0].text.lower() or "unknown" in result.content[0].text.lower()
    )


def test_resolve_workspace_tool(tmp_path: Path):
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    server = _make(tmp_path)

    async def call():
        return await server.call_tool("resolve_workspace", {"path": str(tmp_path)})

    result = asyncio.run(call())
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["workspace_id"] == "default"
    assert Path(payload["matched_root"]) == tmp_path.resolve()
