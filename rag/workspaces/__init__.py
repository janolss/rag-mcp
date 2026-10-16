"""Workspace registry and manifest loading."""

from rag.workspaces.legacy import workspace_from_config
from rag.workspaces.registry import WorkspaceRegistry

__all__ = [
    "WorkspaceRegistry",
    "workspace_from_config",
]
