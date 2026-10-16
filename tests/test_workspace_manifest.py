"""Workspace manifest validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rag.config import Config, IndexConfig, load_config
from rag.workspaces.errors import ManifestNotFoundError, ManifestValidationError
from rag.workspaces.manifest import load_manifest, load_manifests, parse_manifest_dict
from rag.workspaces.registry import WorkspaceRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "workspaces"


def test_load_valid_manifest():
    manifest = load_manifest(FIXTURES / "valid_app.yaml")
    assert manifest.id == "lk_apps"
    assert [root.id for root in manifest.roots] == ["backend", "architecture"]
    workspace = load_manifests([str(FIXTURES / "valid_app.yaml")])[0]
    assert workspace.source_by_id("backend") is not None
    assert workspace.relationships[0].target == "shared-auth"


def test_rejects_duplicate_root_ids(tmp_path: Path):
    data = yaml.safe_load((FIXTURES / "valid_app.yaml").read_text(encoding="utf-8"))
    data["roots"].append(
        {
            "id": "backend",
            "path": "/projects/other",
            "type": "technical_docs",
        }
    )
    with pytest.raises(ManifestValidationError, match="unique"):
        parse_manifest_dict(data)


def test_rejects_unsupported_schema_and_unknown_fields():
    with pytest.raises(ManifestValidationError, match="schema_version"):
        parse_manifest_dict(
            {
                "schema_version": 99,
                "id": "x",
                "name": "X",
                "roots": [{"id": "a", "path": "/tmp/a", "type": "source_code"}],
            }
        )
    with pytest.raises(ManifestValidationError, match="Extra inputs|extra"):
        parse_manifest_dict(
            {
                "schema_version": 1,
                "id": "x",
                "name": "X",
                "unexpected": True,
                "roots": [{"id": "a", "path": "/tmp/a", "type": "source_code"}],
            }
        )


def test_rejects_invalid_relationship_type_and_missing_file(tmp_path: Path):
    with pytest.raises(ManifestValidationError):
        parse_manifest_dict(
            {
                "schema_version": 1,
                "id": "x",
                "name": "X",
                "roots": [{"id": "a", "path": "/tmp/a", "type": "source_code"}],
                "relationships": [{"target": "y", "type": "owns"}],
            }
        )
    with pytest.raises(ManifestNotFoundError):
        load_manifest(tmp_path / "missing.yaml")


def test_config_can_load_multiple_manifests(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {FIXTURES / 'valid_app.yaml'}\n"
        f"  - {FIXTURES / 'valid_shared.yaml'}\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    registry = WorkspaceRegistry.from_config(config)
    assert registry.ids() == ["lk_apps", "shared-auth"]
    assert registry.get("lk_apps").legacy is False


def test_legacy_config_without_manifests_still_works():
    config = Config(index=IndexConfig(repo_root="."))
    registry = WorkspaceRegistry.from_config(config)
    assert registry.ids() == ["default"]
