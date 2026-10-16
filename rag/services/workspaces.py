"""Concrete WorkspaceService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.services.errors import NotFoundError
from rag.services.resolve import registry_for, workspace_to_dict
from rag.workspaces.registry import WorkspaceNotFoundError


class WorkspaceServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def list_workspaces(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        registry = registry_for(self.config)
        return [workspace_to_dict(ws) for ws in registry.list(query=query, tags=tags)]

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        registry = registry_for(self.config)
        try:
            workspace = registry.get(workspace_id)
        except WorkspaceNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        payload = workspace_to_dict(workspace)
        payload["sources"] = [
            {
                "id": source.id,
                "type": source.type,
                "root": source.root,
                "adapter": source.adapter,
                "status": source.status,
                "bucket": source.bucket,
                "description": source.description,
                "include": list(source.include),
                "exclude": list(source.exclude),
            }
            for source in workspace.sources
        ]
        payload["relationships"] = [
            {
                "target": rel.target,
                "type": rel.type,
                "description": rel.description,
            }
            for rel in workspace.relationships
        ]
        return payload
