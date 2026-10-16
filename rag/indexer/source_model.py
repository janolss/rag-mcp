"""Resolve explicit Source objects for indexing without activating new roots yet."""

from __future__ import annotations

from rag.config import Config
from rag.domain.models import Source, Workspace
from rag.workspaces import WorkspaceRegistry


def sources_for_workspace(workspace: Workspace) -> tuple[Source, ...]:
    """Return registered sources, preserving declaration order."""
    return tuple(workspace.sources)


def resolve_workspace_sources(
    config: Config,
    *,
    workspace_id: str | None = None,
) -> tuple[Workspace, tuple[Source, ...]]:
    """
    Resolve sources for a workspace.

    Until path security lands, callers must treat newly declared
    manifest roots as registration-only and continue indexing through the
    legacy glob adapter for the synthetic default workspace.
    """
    registry = WorkspaceRegistry.from_config(config)
    if workspace_id is None:
        ids = registry.ids()
        if len(ids) != 1:
            raise ValueError("workspace_id is required when more than one workspace is registered")
        workspace_id = ids[0]
    workspace = registry.get(workspace_id)
    return workspace, sources_for_workspace(workspace)


def source_specs_from_sources(sources: tuple[Source, ...]) -> list[dict[str, str]]:
    """Serialize sources for status/list APIs."""
    return [
        {
            "id": source.id,
            "type": source.type,
            "root": source.root,
            "adapter": source.adapter,
            "status": source.status,
            "bucket": source.bucket or "",
            "description": source.description,
            "include": ",".join(source.include),
            "exclude": ",".join(source.exclude),
        }
        for source in sources
    ]


def validate_unique_source_ids(sources: tuple[Source, ...]) -> None:
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            raise ValueError(f"duplicate source id: {source.id}")
        seen.add(source.id)
