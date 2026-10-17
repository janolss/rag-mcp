"""Application service layer tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.domain.models import Source, Workspace
from rag.services import (
    NotFoundError,
    ServiceApp,
    ValidationError,
    WorkspaceRequiredError,
)
from rag.workspaces.registry import WorkspaceRegistry
from tests.workspace_fixtures import with_workspace_manifest


def _config(tmp_path: Path, repo: Path | None = None) -> Config:
    root = repo or tmp_path
    return with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="svc"),
            index=IndexConfig(
                repo_root=str(root),
                status_file=str(tmp_path / "status.json"),
                knowledge=["docs/**/*.md"],
                code=["src/**/*.py"],
                sources="knowledge,code",
            ),
            search=SearchConfig(score_threshold=0.0),
        ),
        tmp_path,
    )


def test_list_and_get_workspace(tmp_path: Path):
    app = ServiceApp(_config(tmp_path))
    listed = app.workspaces.list_workspaces()
    assert len(listed) == 1
    assert listed[0]["id"] == "default"
    detail = app.workspaces.get_workspace("default")
    assert detail["id"] == "default"
    assert len(detail["sources"]) >= 1
    with pytest.raises(NotFoundError):
        app.workspaces.get_workspace("missing")


def test_list_sources_for_workspace(tmp_path: Path):
    app = ServiceApp(_config(tmp_path))
    sources = app.sources.list_sources("default")
    ids = {s["id"] for s in sources}
    assert "knowledge" in ids
    assert "code" in ids


def test_get_document_line_range(tmp_path: Path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# Title\nline2\nline3\n", encoding="utf-8")
    app = ServiceApp(_config(tmp_path, repo))
    doc = app.documents.get_document(
        workspace_id="default",
        source_id="knowledge",
        document_id="docs/a.md",
        start_line=2,
        end_line=3,
    )
    assert "line2" in doc["content"]
    assert "line3" in doc["content"]
    assert "# Title" not in doc["content"]
    assert doc["line_count"] == 3


def test_get_document_unknown_source(tmp_path: Path):
    app = ServiceApp(_config(tmp_path))
    with pytest.raises(NotFoundError, match="unknown source"):
        app.documents.get_document(
            workspace_id="default",
            source_id="nope",
            document_id="docs/a.md",
        )


def test_search_requires_workspace_in_multi(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)

    class FakeRegistry(WorkspaceRegistry):
        @classmethod
        def from_config(cls, _config):
            return cls(
                [
                    Workspace(
                        id="one",
                        name="One",
                        sources=(Source(id="knowledge", type="docs", root="."),),
                    ),
                    Workspace(
                        id="two",
                        name="Two",
                        sources=(Source(id="knowledge", type="docs", root="."),),
                    ),
                ]
            )

    monkeypatch.setattr("rag.services.resolve.WorkspaceRegistry", FakeRegistry)
    app = ServiceApp(config)
    with pytest.raises(WorkspaceRequiredError):
        app.search.search(query="hello")
    with pytest.raises(ValidationError, match="query cannot be empty"):
        app.search.search(workspace_id="one", query="  ")


def test_status_includes_workspace(tmp_path: Path):
    app = ServiceApp(_config(tmp_path))
    status = app.status.get_index_status(workspace_id="default")
    assert status["workspace_id"] == "default"
    assert "points_count" in status
