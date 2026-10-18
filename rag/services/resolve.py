"""Helpers for resolving workspace_id in single- vs multi-workspace mode."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.domain.models import Workspace
from rag.services.errors import (
    AmbiguousWorkspaceError,
    NotFoundError,
    WorkspaceRequiredError,
)
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


def normalize_source_root(config: Config, root: str) -> Path:
    """Resolve a source root the same way as DocumentService (abs vs repo-relative)."""
    source_root = Path(root)
    if not source_root.is_absolute():
        return (config.repo_root_path / source_root).resolve()
    return source_root.resolve()


def normalize_resolve_path(path: str | None) -> Path:
    """Normalize caller path; empty / ``.`` means process cwd."""
    text = (path or "").strip() or "."
    return Path(text).expanduser().resolve()


def resolve_workspace_by_path(
    config: Config,
    path: str | None,
    *,
    workspaces: Sequence[Workspace] | None = None,
) -> dict[str, Any]:
    """
    Map a filesystem path to a registered workspace via longest-prefix source root.

    When ``workspaces`` is omitted, all registered workspaces are considered.
    Raises ``NotFoundError`` when nothing matches, or ``AmbiguousWorkspaceError``
    when multiple workspaces share the same longest matching root depth.
    """
    canonical = normalize_resolve_path(path)
    candidates_pool = list(workspaces) if workspaces is not None else registry_for(config).list()

    matches: list[dict[str, Any]] = []
    best_len = -1
    for workspace in candidates_pool:
        for source in workspace.sources:
            root = normalize_source_root(config, source.root)
            try:
                canonical.relative_to(root)
            except ValueError:
                continue
            root_len = len(root.parts)
            hit = {
                "workspace_id": workspace.id,
                "name": workspace.name,
                "matched_root": str(root),
                "source_id": source.id,
                "path": str(canonical),
                "_root_len": root_len,
            }
            if root_len > best_len:
                best_len = root_len
                matches = [hit]
            elif root_len == best_len:
                matches.append(hit)

    if not matches:
        raise NotFoundError(f"no workspace matches path {str(canonical)!r}")

    # Collapse multiple source hits within the same workspace at equal depth.
    by_workspace: dict[str, dict[str, Any]] = {}
    for hit in matches:
        wid = hit["workspace_id"]
        if wid not in by_workspace:
            by_workspace[wid] = hit

    unique = list(by_workspace.values())
    if len(unique) > 1:
        candidates = [
            {
                "workspace_id": item["workspace_id"],
                "name": item["name"],
                "matched_root": item["matched_root"],
                "source_id": item["source_id"],
            }
            for item in unique
        ]
        raise AmbiguousWorkspaceError(
            f"ambiguous workspace for path {str(canonical)!r}: "
            f"{len(candidates)} workspaces match at the same root depth",
            path=str(canonical),
            candidates=candidates,
        )

    winner = unique[0]
    return {
        "workspace_id": winner["workspace_id"],
        "name": winner["name"],
        "matched_root": winner["matched_root"],
        "source_id": winner["source_id"],
        "path": winner["path"],
    }
