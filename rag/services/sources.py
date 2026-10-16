"""Concrete SourceService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.indexer.source_model import resolve_workspace_sources, source_specs_from_sources
from rag.security.access import AccessDenied, authorize_source, authorize_workspace
from rag.security.http_auth import require_principal
from rag.services.errors import ServiceError
from rag.services.resolve import require_workspace


class SourceServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def list_sources(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        principal = require_principal()
        workspace = require_workspace(self.config, workspace_id)
        try:
            authorize_workspace(principal, workspace.id)
        except AccessDenied as exc:
            raise ServiceError(str(exc)) from exc
        _, sources = resolve_workspace_sources(self.config, workspace_id=workspace.id)
        allowed = [s for s in sources if principal.allows_source(s.id)]
        for source in allowed:
            try:
                authorize_source(principal, source.id)
            except AccessDenied as exc:
                raise ServiceError(str(exc)) from exc
        return source_specs_from_sources(tuple(allowed))
