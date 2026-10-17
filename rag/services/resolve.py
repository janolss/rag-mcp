"""Helpers for resolving workspace_id in single- vs multi-workspace mode."""

from __future__ import annotations

from rag.config import Config
from rag.domain.models import Workspace
from rag.services.errors import NotFoundError, WorkspaceRequiredError
from rag.workspaces.registry import WorkspaceNotFoundError, WorkspaceRegistry


def registry_for(config: Config) -> WorkspaceRegistry:
    return WorkspaceRegistry.from_config(config)


def resolve_workspace_id(
    config: Config,
    workspace_id: str | None,
    *,
    required: bool = True,
) -> str | None:
    """
    Resolve a caller workspace_id.

    When exactly one workspace is registered, its id is inferred when omitted.
    Multi-workspace configs require an explicit id when ``required`` is True.
    """
    registry = registry_for(config)
    if workspace_id:
        try:
            registry.get(workspace_id)
        except WorkspaceNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        return workspace_id

    ids = registry.ids()
    if len(ids) == 1:
        return ids[0]
    if not required:
        return None
    raise WorkspaceRequiredError(
        "workspace_id is required when more than one workspace is registered"
    )


def require_workspace(config: Config, workspace_id: str | None) -> Workspace:
    resolved = resolve_workspace_id(config, workspace_id, required=True)
    assert resolved is not None
    try:
        return registry_for(config).get(resolved)
    except WorkspaceNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc


def workspace_to_dict(workspace: Workspace) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "technologies": list(workspace.technologies),
        "tags": list(workspace.tags),
        "instructions": list(workspace.instructions),
        "legacy": workspace.legacy,
        "root_path": workspace.root_path,
        "source_count": len(workspace.sources),
        "relationship_count": len(workspace.relationships),
        "metadata": dict(workspace.metadata),
    }
