"""HTTP / stdio transport config helpers."""

from types import SimpleNamespace

import pytest

from rag.config import (
    Config,
    McpConfig,
    mcp_public_url,
    mcp_run_kwargs,
    normalize_mcp_transport,
)
from rag.mcp_http import endpoint_urls
from rag.mcp_server import apply_cli_overrides


def test_normalize_transport_aliases():
    assert normalize_mcp_transport("http") == "http"
    assert normalize_mcp_transport("both") == "http"
    assert normalize_mcp_transport("streamable_http") == "streamable-http"
    assert normalize_mcp_transport("SSE") == "sse"
    with pytest.raises(ValueError):
        normalize_mcp_transport("websocket")


def test_stdio_run_kwargs():
    config = Config(mcp=McpConfig(transport="stdio"))
    assert mcp_run_kwargs(config) == {"transport": "stdio"}
    assert mcp_public_url(config) is None


def test_streamable_http_run_kwargs_and_url():
    config = Config(
        mcp=McpConfig(transport="streamable-http", host="127.0.0.1", port=8765, path="")
    )
    assert mcp_run_kwargs(config) == {
        "transport": "streamable-http",
        "host": "127.0.0.1",
        "port": 8765,
        "streamable_http_path": "/mcp",
        "stateless_http": True,
    }
    assert mcp_public_url(config) == "http://127.0.0.1:8765/mcp"


def test_sse_run_kwargs_and_url():
    config = Config(
        mcp=McpConfig(transport="sse", host="0.0.0.0", port=9000, path="/events")
    )
    kwargs = mcp_run_kwargs(config)
    assert kwargs["transport"] == "sse"
    assert kwargs["sse_path"] == "/events"
    assert kwargs["message_path"] == "/messages/"
    assert mcp_public_url(config) == "http://0.0.0.0:9000/events"


def test_dual_http_urls():
    config = Config(mcp=McpConfig(transport="http", host="127.0.0.1", port=8000))
    assert mcp_public_url(config) == "http://127.0.0.1:8000/mcp"
    urls = endpoint_urls(config)
    assert urls["streamable-http"] == "http://127.0.0.1:8000/mcp"
    assert urls["sse"] == "http://127.0.0.1:8000/sse"
    assert urls["sse_messages"] == "http://127.0.0.1:8000/messages/"
    with pytest.raises(ValueError):
        mcp_run_kwargs(config)


def test_cli_overrides_transport():
    config = Config(mcp=McpConfig(transport="stdio", port=8000))
    args = SimpleNamespace(transport="http", host="127.0.0.1", port=8123, path="/mcp")
    apply_cli_overrides(config, args)
    assert config.mcp.transport == "http"
    assert config.mcp.port == 8123
    assert mcp_public_url(config) == "http://127.0.0.1:8123/mcp"
