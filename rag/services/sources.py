"""Concrete SourceService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.indexer.source_model import resolve_workspace_sources, source_specs_from_sources
from rag.mcp_results import resource_error, resource_ok
from rag.security.access import AccessDenied, authorize_source, authorize_workspace
from rag.security.http_auth import require_principal
from rag.services.errors import ForbiddenError
from rag.services.resolve import registry_for, require_workspace
from rag.store import QdrantLockError


class SourceServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def list_sources(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        principal = require_principal()
        if workspace_id is None:
            return self._list_visible_workspaces_sources(principal)

        workspace = require_workspace(self.config, workspace_id)
        try:
            authorize_workspace(principal, workspace.id)
        except AccessDenied as exc:
            raise ForbiddenError(str(exc)) from exc
        _, sources = resolve_workspace_sources(self.config, workspace_id=workspace.id)
        allowed = [s for s in sources if principal.allows_source(s.id)]
        for source in allowed:
            try:
                authorize_source(principal, source.id)
            except AccessDenied as exc:
                raise ForbiddenError(str(exc)) from exc
        return source_specs_from_sources(tuple(allowed))

    def _list_visible_workspaces_sources(self, principal) -> list[dict[str, Any]]:
        registry = registry_for(self.config)
        rows: list[dict[str, Any]] = []
        for workspace in registry.list():
            if not principal.allows_workspace(workspace.id):
                continue
            _, sources = resolve_workspace_sources(self.config, workspace_id=workspace.id)
            allowed = [s for s in sources if principal.allows_source(s.id)]
            rows.append(
                {
                    "workspace_id": workspace.id,
                    "name": workspace.name,
                    "sources": source_specs_from_sources(tuple(allowed)),
                }
            )
        return rows

    def sources_resource(self) -> str:
        try:
            payload = {"workspaces": self._list_visible_workspaces_sources(require_principal())}
            return resource_ok(payload)
        except (AccessDenied, ForbiddenError, QdrantLockError) as exc:
            return resource_error(str(exc))
        except Exception as exc:
            return resource_error(f"failed to list sources: {exc}")
