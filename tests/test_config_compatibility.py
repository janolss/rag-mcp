"""Legacy config continues to expose a synthetic default workspace."""

from __future__ import annotations

from pathlib import Path

from rag.config import (
    CapabilitiesConfig,
    Config,
    IndexConfig,
    McpConfig,
    load_config,
)
from rag.workspaces import WorkspaceRegistry, workspace_from_config


def test_load_config_still_works_without_manifests(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "mcp:\n  name: test-rag\n  transport: stdio\nindex:\n  repo_root: .\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.mcp.name == "test-rag"
    registry = WorkspaceRegistry.from_config(config)
    assert registry.ids() == ["default"]
    workspace = registry.get("default")
    assert workspace.legacy is True
    assert workspace.name == "test-rag"


def test_workspace_from_config_maps_buckets(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = Config(
        index=IndexConfig(
            repo_root=str(repo),
            knowledge=["docs/**/*.md"],
            code=["src/**/*.py"],
            lis=[],
            sources="knowledge,code",
        ),
        mcp=McpConfig(
            name="demo",
            capabilities=CapabilitiesConfig(knowledge=True, code=True, lis=False),
        ),
    )
    workspace = workspace_from_config(config)
    assert workspace.id == "default"
    assert [s.id for s in workspace.sources] == ["knowledge", "code"]
    assert workspace.source_by_id("knowledge").bucket == "knowledge"
    assert workspace.source_by_id("code").include == ("src/**/*.py",)
