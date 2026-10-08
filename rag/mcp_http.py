"""HTTP transports for MCP (streamable-http, SSE, or both on one port)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import anyio

from rag.config import Config, mcp_http_path, normalize_mcp_transport

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)


def _message_path(config: Config) -> str:
    message_path = (config.mcp.message_path or "/messages/").strip() or "/messages/"
    return message_path if message_path.startswith("/") else f"/{message_path}"


def endpoint_urls(config: Config) -> dict[str, str]:
    """Advertised client URLs for the active HTTP transport(s)."""
    host = config.mcp.host
    port = int(config.mcp.port)
    base = f"http://{host}:{port}"
    transport = normalize_mcp_transport(config.mcp.transport)
    urls: dict[str, str] = {}
    if transport == "streamable-http":
        urls["streamable-http"] = f"{base}{mcp_http_path(config)}"
    elif transport == "sse":
        urls["sse"] = f"{base}{mcp_http_path(config)}"
        urls["sse_messages"] = f"{base}{_message_path(config)}"
    elif transport == "http":
        urls["streamable-http"] = f"{base}/mcp"
        urls["sse"] = f"{base}/sse"
        urls["sse_messages"] = f"{base}{_message_path(config)}"
    return urls


async def _serve_uvicorn(app: Any, *, host: str, port: int, log_level: str) -> None:
    import uvicorn

    uv_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
    )
    server = uvicorn.Server(uv_config)
    await server.serve()


def _root_info_route(config: Config):
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    urls = endpoint_urls(config)

    async def root(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": config.mcp.name,
                "transport": normalize_mcp_transport(config.mcp.transport),
                "endpoints": urls,
                "hint": (
                    "Modern MCP URL clients should use endpoints['streamable-http'] "
                    "(POST). Legacy SSE clients use GET endpoints['sse'] and POST to "
                    "endpoints['sse_messages']. Root POST is not an MCP endpoint."
                ),
            }
        )

    return Route("/", endpoint=root, methods=["GET", "POST"])


async def run_http_async(mcp: MCPServer, config: Config) -> None:
    """Run streamable-http, SSE, or both (transport=http) under uvicorn."""
    transport = normalize_mcp_transport(config.mcp.transport)
    host = config.mcp.host
    port = int(config.mcp.port)
    log_level = config.log_level

    if transport == "streamable-http":
        path = mcp_http_path(config)
        app = mcp.streamable_http_app(
            host=host,
            streamable_http_path=path,
            stateless_http=bool(config.mcp.stateless_http),
        )
        app.routes.insert(0, _root_info_route(config))
        await _serve_uvicorn(app, host=host, port=port, log_level=log_level)
        return

    if transport == "sse":
        path = mcp_http_path(config)
        app = mcp.sse_app(
            host=host,
            sse_path=path,
            message_path=_message_path(config),
        )
        app.routes.insert(0, _root_info_route(config))
        await _serve_uvicorn(app, host=host, port=port, log_level=log_level)
        return

    if transport != "http":
        raise ValueError(f"run_http_async does not support transport={transport!r}")

    # Dual: streamable-http at /mcp + SSE at /sse (and /messages/)
    stream_app = mcp.streamable_http_app(
        host=host,
        streamable_http_path="/mcp",
        stateless_http=bool(config.mcp.stateless_http),
    )
    sse_app = mcp.sse_app(
        host=host,
        sse_path="/sse",
        message_path=_message_path(config),
    )
    stream_app.routes.insert(0, _root_info_route(config))
    stream_app.routes.extend(sse_app.routes)
    logger.info(
        "Dual HTTP MCP: streamable-http=/mcp sse=/sse messages=%s",
        _message_path(config),
    )
    await _serve_uvicorn(stream_app, host=host, port=port, log_level=log_level)


def run_http(mcp: MCPServer, config: Config) -> None:
    anyio.run(lambda: run_http_async(mcp, config))
