"""Workspace registry and manifest loading."""

from rag.workspaces.legacy import workspace_from_config
from rag.workspaces.manifest import load_manifest, load_manifests, parse_manifest_dict
from rag.workspaces.registry import WorkspaceRegistry

__all__ = [
    "WorkspaceRegistry",
    "load_manifest",
    "load_manifests",
    "parse_manifest_dict",
    "workspace_from_config",
]
