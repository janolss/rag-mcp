"""Resolve explicit Source objects and walk them for indexing."""

from __future__ import annotations

from pathlib import Path

from rag.config import Config
from rag.domain.models import Source, Workspace
from rag.indexer.walk import walk_source
from rag.security.paths import PathSecurityPolicy
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

    Manifest and legacy sources are both active for indexing. When more than
    one workspace is registered, callers must pass ``workspace_id``.
    """
    registry = WorkspaceRegistry.from_config(config)
    if workspace_id is None:
        ids = registry.ids()
        if len(ids) != 1:
            raise ValueError("workspace_id is required when more than one workspace is registered")
        workspace_id = ids[0]
    workspace = registry.get(workspace_id)
    return workspace, sources_for_workspace(workspace)


def source_specs_from_sources(sources: tuple[Source, ...] | list[Source]) -> list[dict[str, str]]:
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


def registered_source_roots(
    config: Config,
    *,
    workspace_id: str | None = None,
) -> list[Path]:
    """Absolute roots declared by registered sources (optionally one workspace)."""
    registry = WorkspaceRegistry.from_config(config)
    workspaces = [registry.get(workspace_id)] if workspace_id is not None else registry.list()
    roots: list[Path] = []
    seen: set[Path] = set()
    for workspace in workspaces:
        for source in workspace.sources:
            root = Path(source.root).resolve()
            if root in seen:
                continue
            seen.add(root)
            roots.append(root)
    return roots


def discover_workspace_files(
    config: Config,
    *,
    workspace_id: str | None = None,
    source_id: str | None = None,
    policy: PathSecurityPolicy | None = None,
) -> list[tuple[Path, str, str, str]]:
    """
    Discover files for a workspace by walking each Source root.

    Returns ``(absolute_path, source_id, bucket, path_identity)``. Path identity
    is relative to the workspace/source root (not ``config.repo_root``) so
    ``index.apps`` and documentation prefixes match. When ``source_id`` is set,
    only that source is walked.
    """
    from rag.indexer.walk import path_identity_for_indexing

    workspace, sources = resolve_workspace_sources(config, workspace_id=workspace_id)
    active = policy or PathSecurityPolicy()
    discovered: list[tuple[Path, str, str, str]] = []
    for source in sources:
        if source_id is not None and source.id != source_id:
            continue
        for path, sid, bucket in walk_source(
            source,
            ignore_dirs=config.index.ignore_dirs,
            policy=active,
            identity_root=Path(source.root),
        ):
            identity = path_identity_for_indexing(
                path,
                workspace_root=workspace.root_path,
                source_root=source.root,
                repo_root=config.repo_root_path,
            )
            discovered.append((path, sid, bucket, identity))
    # Prefer later sources when the same absolute path appears twice.
    by_path: dict[Path, tuple[Path, str, str, str]] = {}
    for item in discovered:
        by_path[item[0]] = item
    files = sorted(by_path.values(), key=lambda item: item[0].as_posix())
    return files
