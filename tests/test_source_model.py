"""Explicit source model tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, IndexConfig, load_config
from rag.domain.models import Source, Workspace
from rag.indexer.source_model import (
    resolve_workspace_sources,
    source_specs_from_sources,
    validate_unique_source_ids,
)
from rag.workspaces.registry import WorkspaceRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "workspaces"


def test_legacy_config_exposes_at_least_two_sources(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = Config(
        index=IndexConfig(
            repo_root=str(repo),
            knowledge=["docs/**/*.md"],
            code=["src/**/*.py"],
            sources="all",
        )
    )
    workspace, sources = resolve_workspace_sources(config)
    assert workspace.id == "default"
    assert len(sources) >= 2
    assert {s.id for s in sources} >= {"knowledge", "code"}
    validate_unique_source_ids(sources)


def test_manifest_sources_preserve_roots_and_buckets(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {FIXTURES / 'valid_app.yaml'}\n"
        f"  - {FIXTURES / 'valid_shared.yaml'}\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    _workspace, sources = resolve_workspace_sources(config, workspace_id="lk_apps")
    assert [s.id for s in sources] == ["backend", "architecture"]
    assert sources[0].root.endswith("lk_apps")
    assert sources[0].bucket == "code"
    assert sources[1].bucket == "knowledge"
    payload = source_specs_from_sources(sources)
    assert payload[0]["status"] == "not_indexed"


def test_duplicate_source_ids_rejected():
    sources = (
        Source(id="backend", type="source_code", root="/a"),
        Source(id="backend", type="technical_docs", root="/b"),
    )
    with pytest.raises(ValueError, match="duplicate source id"):
        validate_unique_source_ids(sources)


def test_multiple_workspaces_can_share_source_id_namespace():
    registry = WorkspaceRegistry(
        [
            Workspace(
                id="a",
                name="A",
                sources=(Source(id="s1", type="source_code", root="/a"),),
            ),
            Workspace(
                id="b",
                name="B",
                sources=(Source(id="s1", type="source_code", root="/b"),),
            ),
        ]
    )
    assert len(registry) == 2
    assert registry.get("a").source_by_id("s1") is not None
    assert registry.get("b").source_by_id("s1") is not None
