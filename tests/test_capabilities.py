"""Capabilities gate indexing buckets and MCP tool registration."""

from __future__ import annotations

import asyncio

from rag.config import (
    CapabilitiesConfig,
    Config,
    IndexConfig,
    McpConfig,
    QdrantConfig,
    parse_sources_mode,
    resolve_mcp_instructions,
)
from rag.indexer.sources import selected_sources_for_config
from rag.mcp_server import create_mcp_server
from rag.runtime import RagRuntime


def test_parse_sources_mode_all_and_subset():
    assert parse_sources_mode("all") == {"knowledge", "code", "lis"}
    assert parse_sources_mode("knowledge,lis") == {"knowledge", "lis"}
    assert parse_sources_mode("code") == {"code"}


def test_enabled_buckets_intersects_capabilities():
    config = Config(
        index=IndexConfig(sources="all", lis=["lis/**/*.md"]),
        mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=True, code=False, lis=True)),
    )
    assert config.enabled_buckets() == {"knowledge", "lis"}
    specs = selected_sources_for_config(config)
    buckets = {s.bucket for s in specs}
    assert buckets == {"knowledge", "lis"}
    assert any(s.pattern == "lis/**/*.md" for s in specs)


def test_resolve_instructions_appends_lis_block():
    config = Config(
        mcp=McpConfig(
            instructions="Base instructions only.",
            capabilities=CapabilitiesConfig(lis=True),
        )
    )
    text = resolve_mcp_instructions(config)
    assert "Base instructions only." in text
    assert "search_lis" in text


def test_create_mcp_server_registers_search_lis_only_when_enabled(tmp_path):
    from pathlib import Path

    from tests.workspace_fixtures import with_workspace_manifest

    tmp_path = Path(tmp_path)
    base = dict(
        qdrant=QdrantConfig(mode="memory", collection="cap_test"),
        index=IndexConfig(repo_root=str(tmp_path), sources="all", lis=["lis/**/*.md"]),
    )

    off = with_workspace_manifest(
        Config(
            **base,
            mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=True, code=True, lis=False)),
        ),
        tmp_path,
        manifest_name="off.yaml",
    )
    on = with_workspace_manifest(
        Config(
            **base,
            mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=False, code=False, lis=True)),
        ),
        tmp_path,
        manifest_name="on.yaml",
    )

    async def names(config: Config) -> set[str]:
        server = create_mcp_server(config, RagRuntime(config))
        tools = await server.list_tools()
        return {t.name for t in tools}

    off_names = asyncio.run(names(off))
    on_names = asyncio.run(names(on))

    assert "search_knowledge" in off_names
    assert "search_code" in off_names
    assert "search_lis" not in off_names

    assert "search_lis" in on_names
    assert "search_knowledge" not in on_names
    assert "search_code" not in on_names
    assert "trace_requirement" not in on_names
    assert "get_context_pack" in on_names
