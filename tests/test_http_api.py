"""ASGI tests for /api/v1 (no network server)."""

from __future__ import annotations

import json
from pathlib import Path

from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.http_api import create_api_app
from rag.services import ServiceApp
from starlette.testclient import TestClient


def _config(tmp_path: Path, repo: Path | None = None) -> Config:
    root = repo or tmp_path
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="http_api"),
        index=IndexConfig(
            repo_root=str(root),
            status_file=str(tmp_path / "status.json"),
            knowledge=["docs/**/*.md"],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )


def test_list_workspaces_and_sources(tmp_path: Path):
    config = _config(tmp_path)
    client = TestClient(create_api_app(config))
    root = client.get("/api/v1")
    assert root.status_code == 200
    assert root.json()["api"] == "v1"

    listed = client.get("/api/v1/workspaces")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "default"

    detail = client.get("/api/v1/workspaces/default")
    assert detail.status_code == 200
    assert detail.json()["id"] == "default"

    sources = client.get("/api/v1/workspaces/default/sources")
    assert sources.status_code == 200
    assert any(s["id"] == "knowledge" for s in sources.json())

    missing = client.get("/api/v1/workspaces/nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_get_document_and_status(tmp_path: Path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# Hello\nworld\n", encoding="utf-8")
    config = _config(tmp_path, repo)
    client = TestClient(create_api_app(config, ServiceApp(config)))

    doc = client.get(
        "/api/v1/documents",
        params={
            "workspace_id": "default",
            "source_id": "knowledge",
            "document_id": "docs/a.md",
            "start_line": 1,
            "end_line": 1,
        },
    )
    assert doc.status_code == 200
    body = doc.json()
    assert "Hello" in body["content"]
    assert "world" not in body["content"]
    assert "absolute_path" not in body

    status = client.get("/api/v1/index/status", params={"workspace_id": "default"})
    assert status.status_code == 200
    assert status.json()["workspace_id"] == "default"


def test_search_validation_error(tmp_path: Path):
    client = TestClient(create_api_app(_config(tmp_path)))
    resp = client.post("/api/v1/search", content=json.dumps({"query": ""}))
    assert resp.status_code == 400


def test_rest_mcp_parity_list_workspaces(tmp_path: Path):
    config = _config(tmp_path)
    services = ServiceApp(config)
    via_service = services.workspaces.list_workspaces()
    client = TestClient(create_api_app(config, services))
    via_rest = client.get("/api/v1/workspaces").json()
    assert via_rest == via_service
