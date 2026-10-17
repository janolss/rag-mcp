"""Package version for MCP server metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_FALLBACK = "0.2.0"


def package_version() -> str:
    try:
        return version("rag-mcp")
    except PackageNotFoundError:
        return _FALLBACK
