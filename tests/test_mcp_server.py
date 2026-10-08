import asyncio

from rag.config import CapabilitiesConfig, Config, IndexConfig, McpConfig, QdrantConfig
from rag.mcp_server import create_mcp_server
from rag.runtime import RagRuntime


def test_mcp_server_registers_tools_resources_and_prompts():
    config = Config(
        qdrant=QdrantConfig(mode="memory", collection="mcp_reg"),
        index=IndexConfig(sources="all"),
        mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=True, code=True, lis=False)),
    )
    server = create_mcp_server(config, RagRuntime(config))

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
