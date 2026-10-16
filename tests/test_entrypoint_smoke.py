"""Smoke tests for package imports and entrypoints after the runtime gate."""

from __future__ import annotations

import importlib

from rag.config import load_config
from rag.services.contracts import (
    DocumentService,
    SearchService,
    SourceService,
    StatusService,
    WorkspaceService,
)


def test_core_modules_import():
    for module_name in (
        "rag",
        "rag.config",
        "rag.cli",
        "rag.mcp_server",
        "rag.mcp_http",
        "rag.runtime",
        "rag.store",
        "rag.services",
        "rag.services.contracts",
    ):
        module = importlib.import_module(module_name)
        assert module is not None


def test_default_config_loads_stdio_and_http_shapes():
    config = load_config()
    assert config.mcp.transport == "stdio"
    assert config.mcp.host == "127.0.0.1"
    assert int(config.mcp.port) == 8000
    assert config.mcp.capabilities.knowledge is True
    assert config.mcp.capabilities.code is True


def test_service_protocols_are_runtime_checkable():
    for protocol in (
        WorkspaceService,
        SourceService,
        SearchService,
        DocumentService,
        StatusService,
    ):
        assert getattr(protocol, "_is_runtime_protocol", False) is True


def test_cli_and_mcp_entrypoints_are_callable():
    from rag.cli import main as cli_main
    from rag.mcp_server import main as mcp_main

    assert callable(cli_main)
    assert callable(mcp_main)
