"""Tests for path → workspace resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.domain.models import Source, Workspace
from rag.security.access import Principal
from rag.security.http_auth import set_principal
from rag.services import AmbiguousWorkspaceError, NotFoundError, ServiceApp, ValidationError
from rag.services.resolve import resolve_workspace_by_path
from rag.workspaces.registry import WorkspaceRegistry
from tests.workspace_fixtures import write_workspace_manifest


def _base_config(tmp_path: Path, repo: Path, manifests: list[Path]) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="resolve_ws"),
        index=IndexConfig(
            repo_root=str(repo),
            status_file=str(tmp_path / "status.json"),
            knowledge=["**/*.md"],
            code=["**/*.py"],
            sources="all",
        ),
        search=SearchConfig(score_threshold=0.0),
        workspace_manifests=[str(p) for p in manifests],
    )


def test_resolve_unique_absolute_root(tmp_path: Path):
    repo_a = tmp_path / "app_a"
    repo_b = tmp_path / "app_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "main.py").write_text("print(1)\n", encoding="utf-8")

    m_a = write_workspace_manifest(
        tmp_path / "a.yaml",
        workspace_id="app_a",
        root=repo_a,
        sources=[
            {
                "id": "code",
                "path": str(repo_a),
                "type": "source_code",
                "include": ["**/*.py"],
            }
        ],
    )
    m_b = write_workspace_manifest(
        tmp_path / "b.yaml",
        workspace_id="app_b",
        root=repo_b,
        sources=[
            {
                "id": "code",
                "path": str(repo_b),
                "type": "source_code",
                "include": ["**/*.py"],
            }
        ],
    )
    config = _base_config(tmp_path, tmp_path, [m_a, m_b])
    app = ServiceApp(config)

    hit = app.workspaces.resolve_workspace(str(repo_a / "main.py"))
    assert hit["workspace_id"] == "app_a"
    assert hit["source_id"] == "code"
    assert Path(hit["matched_root"]) == repo_a.resolve()
    assert Path(hit["path"]) == (repo_a / "main.py").resolve()


def test_resolve_longest_prefix_nested_sources(tmp_path: Path):
    repo = tmp_path / "mono"
    nested = repo / "packages" / "api"
    nested.mkdir(parents=True)
    (nested / "x.py").write_text("x\n", encoding="utf-8")

    manifest = tmp_path / "mono.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "mono",
                "name": "Mono",
                "roots": [
                    {
                        "id": "repo",
                        "path": str(repo),
                        "type": "source_code",
                        "include": ["**/*.py"],
                    },
                    {
                        "id": "api",
                        "path": str(nested),
                        "type": "source_code",
                        "include": ["**/*.py"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = _base_config(tmp_path, repo, [manifest])
    hit = resolve_workspace_by_path(config, str(nested / "x.py"))
    assert hit["workspace_id"] == "mono"
    assert hit["source_id"] == "api"
    assert Path(hit["matched_root"]) == nested.resolve()


def test_resolve_relative_root_via_repo_root(tmp_path: Path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# hi\n", encoding="utf-8")

    manifest = write_workspace_manifest(
        tmp_path / "rel.yaml",
        workspace_id="rel",
        root=repo,
        sources=[
            {
                "id": "knowledge",
                "path": "docs",
                "type": "architecture_docs",
                "include": ["**/*.md"],
            }
        ],
    )
    config = _base_config(tmp_path, repo, [manifest])
    hit = ServiceApp(config).workspaces.resolve_workspace(str(docs / "a.md"))
    assert hit["workspace_id"] == "rel"
    assert hit["source_id"] == "knowledge"
    assert Path(hit["matched_root"]) == docs.resolve()


def test_resolve_no_match(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    manifest = write_workspace_manifest(tmp_path / "one.yaml", workspace_id="one", root=repo)
    config = _base_config(tmp_path, repo, [manifest])
    with pytest.raises(NotFoundError, match="no workspace matches"):
        ServiceApp(config).workspaces.resolve_workspace(str(elsewhere / "x.txt"))


def test_resolve_ambiguous_equal_depth(tmp_path: Path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "f.py").write_text("f\n", encoding="utf-8")

    config = _base_config(tmp_path, shared, [])

    class FakeRegistry(WorkspaceRegistry):
        @classmethod
        def from_config(cls, _config):
            root = str(shared.resolve())
            return cls(
                [
                    Workspace(
                        id="one",
                        name="One",
                        sources=(Source(id="code", type="source_code", root=root),),
                        root_path=root,
                    ),
                    Workspace(
                        id="two",
                        name="Two",
                        sources=(Source(id="code", type="source_code", root=root),),
                        root_path=root,
                    ),
                ]
            )

    monkeypatch.setattr("rag.services.resolve.WorkspaceRegistry", FakeRegistry)
    with pytest.raises(AmbiguousWorkspaceError) as exc_info:
        resolve_workspace_by_path(config, str(shared / "f.py"))
    err = exc_info.value
    assert {c["workspace_id"] for c in err.candidates} == {"one", "two"}
    assert err.path == str((shared / "f.py").resolve())


def test_resolve_empty_path_validation(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = write_workspace_manifest(tmp_path / "one.yaml", workspace_id="one", root=repo)
    config = _base_config(tmp_path, repo, [manifest])
    with pytest.raises(ValidationError, match="path cannot be empty"):
        ServiceApp(config).workspaces.resolve_workspace("  ")


def test_resolve_auth_filters_invisible_workspace(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("a\n", encoding="utf-8")
    (repo_b / "b.py").write_text("b\n", encoding="utf-8")

    m_a = write_workspace_manifest(
        tmp_path / "a.yaml",
        workspace_id="alpha",
        root=repo_a,
        sources=[
            {"id": "code", "path": str(repo_a), "type": "source_code", "include": ["**/*.py"]}
        ],
    )
    m_b = write_workspace_manifest(
        tmp_path / "b.yaml",
        workspace_id="beta",
        root=repo_b,
        sources=[
            {"id": "code", "path": str(repo_b), "type": "source_code", "include": ["**/*.py"]}
        ],
    )
    config = _base_config(tmp_path, tmp_path, [m_a, m_b])
    app = ServiceApp(config)

    set_principal(
        Principal(
            subject="reader",
            anonymous=False,
            workspace_allowlist=frozenset({"alpha"}),
        )
    )
    try:
        hit = app.workspaces.resolve_workspace(str(repo_a / "a.py"))
        assert hit["workspace_id"] == "alpha"
        with pytest.raises(NotFoundError):
            app.workspaces.resolve_workspace(str(repo_b / "b.py"))
    finally:
        set_principal(None)
