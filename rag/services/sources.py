"""Concrete SourceService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.indexer.source_model import resolve_workspace_sources, source_specs_from_sources
from rag.services.resolve import require_workspace


class SourceServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def list_sources(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        workspace = require_workspace(self.config, workspace_id)
        _, sources = resolve_workspace_sources(self.config, workspace_id=workspace.id)
        return source_specs_from_sources(sources)
