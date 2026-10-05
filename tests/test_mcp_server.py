import asyncio


def test_mcp_server_registers_tools_resources_and_prompts():
    from rag.mcp_server import mcp

    async def list_registrations():
        return (
            await mcp.list_tools(),
            await mcp.list_resources(),
            await mcp.list_prompts(),
        )

    tools, resources, prompts = asyncio.run(list_registrations())

    assert "search_knowledge" in {tool.name for tool in tools}
    assert "rag://status" in {str(resource.uri) for resource in resources}
    assert "change-plan" in {prompt.name for prompt in prompts}
