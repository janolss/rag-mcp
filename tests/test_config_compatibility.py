"""Config load requires workspace_manifests for registry use."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, IndexConfig, load_config
from rag.workspaces import WorkspaceConfigError, WorkspaceRegistry
from tests.workspace_fixtures import with_workspace_manifest, write_workspace_manifest


def test_load_config_without_manifests_loads_but_registry_fails(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "mcp:\n  name: test-rag\n  transport: stdio\nindex:\n  repo_root: .\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.mcp.name == "test-rag"
    with pytest.raises(WorkspaceConfigError, match="workspace_manifests"):
        WorkspaceRegistry.from_config(config)


def test_registry_from_manifest(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    manifest = write_workspace_manifest(
        tmp_path / "ws.yaml",
        workspace_id="demo",
        root=root,
        sources=[
            {
                "id": "knowledge",
                "path": str(root),
                "type": "architecture_docs",
                "include": ["docs/**/*.md"],
            },
            {
                "id": "code",
                "path": str(root),
                "type": "source_code",
                "include": ["src/**/*.py"],
            },
        ],
    )
    config = Config(
        index=IndexConfig(repo_root=str(root), knowledge=["docs/**/*.md"], code=["src/**/*.py"]),
        workspace_manifests=[str(manifest)],
    )
    registry = WorkspaceRegistry.from_config(config)
    assert registry.ids() == ["demo"]
    workspace = registry.get("demo")
    assert workspace.legacy is False
    assert [s.id for s in workspace.sources] == ["knowledge", "code"]


def test_with_workspace_manifest_helper(tmp_path: Path):
    config = with_workspace_manifest(
        Config(index=IndexConfig(repo_root=str(tmp_path), knowledge=["**/*.md"])),
        tmp_path,
    )
    assert WorkspaceRegistry.from_config(config).ids() == ["default"]
