"""Helpers for MCP tool and resource payloads."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent


def tool_text(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


def tool_error(message: str) -> CallToolResult:
    text = message if message.startswith("Error:") else f"Error: {message}"
    return tool_text(text, is_error=True)


def as_tool_result(text: str) -> CallToolResult:
    """Wrap tool text; mark infrastructure/validation Error: strings as isError."""
    if text.startswith("Error:"):
        return tool_text(text, is_error=True)
    return tool_text(text, is_error=False)


def resource_ok(payload: dict[str, Any]) -> str:
    body = {"ok": True, **payload}
    return json.dumps(body, indent=2) + "\n"


def resource_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, indent=2) + "\n"
