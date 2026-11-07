"""Local dashboard, background jobs and access controls."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from rag.config import Config, IndexConfig, McpConfig, QdrantConfig
from rag.http_api import create_api_app
from rag.indexer.jobs import jobs_db_path
from rag.indexer.jobs import run_index_job as original_run_index_job
from rag.indexer.status_store import StatusStore
from rag.mcp_http import _attach_http_routes
from rag.runtime import RagRuntime
from starlette.applications import Starlette
from starlette.testclient import TestClient
from tests.workspace_fixtures import write_workspace_manifest


@pytest.fixture
def config(tmp_path: Path) -> Config:
    manifests = []
    for workspace in ("one", "two"):
        root = tmp_path / workspace
        root.mkdir()
        manifests.append(
            str(
                write_workspace_manifest(root / "workspace.yaml", workspace_id=workspace, root=root)
            )
        )
    return Config(
        workspace_manifests=manifests,
        index=IndexConfig(repo_root=str(tmp_path), status_file=str(tmp_path / "status.json")),
        qdrant=QdrantConfig(mode="local", local_path=str(tmp_path / "qdrant")),
        mcp=McpConfig(host="127.0.0.1"),
    )


def client_for(app: Starlette, *, peer: str = "127.0.0.1") -> TestClient:
    return TestClient(app, base_url="http://localhost:8000", client=(peer, 1234))


def post(client: TestClient, workspace_id: str | None):
    return client.post(
        "/gui/reindex",
        headers={"origin": "http://localhost:8000"},
        json={"workspace_id": workspace_id},
    )


def wait_for_job(config: Config, job_id: str, expected: str) -> None:
    deadline = time.monotonic() + 5
    store = StatusStore(jobs_db_path(config))
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job and job.status == expected:
            return
        time.sleep(0.01)
    pytest.fail(f"Job {job_id} did not become {expected}")


def test_gui_assets_and_mcp_http_mount(config: Config):
    app = Starlette()
    _attach_http_routes(app, config)
    client = client_for(app)
    assert client.get("/").status_code == 200
    assert client.get("/gui").status_code == 200
    assert "RAG MCP dashboard" in client.get("/gui/").text
    assert client.get("/gui/app.js").status_code == 200
    assert client.get("/gui/style.css").status_code == 200
    assert client.get("/gui/unknown").status_code == 404
    assert client.get("/gui/status").json()["server"]["status"] == "ok"
    assert [item["id"] for item in client.get("/gui/indexing-history").json()["workspaces"]] == [
        "one",
        "two",
    ]


def test_reindex_single_all_history_and_conflict(config: Config, monkeypatch: pytest.MonkeyPatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_index(_config, *, workspace_id=None):
        calls.append(workspace_id)
        started.set()
        assert release.wait(5)
        return {"workspace_ids": [workspace_id] if workspace_id else ["one", "two"]}

    monkeypatch.setattr("rag.indexer.run.run_index", fake_index)
    client = client_for(create_api_app(config))
    response = post(client, "one")
    assert response.status_code == 202
    assert started.wait(5)
    assert post(client, None).status_code == 409
    assert client.get("/gui/indexing-history").json()["jobs"][0]["status"] == "running"
    release.set()
    wait_for_job(config, response.json()["job_id"], "succeeded")

    # The worker may still be releasing its in-memory admission lock.
    deadline = time.monotonic() + 5
    while True:
        response = post(client, None)
        if response.status_code != 409 or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert response.status_code == 202
    wait_for_job(config, response.json()["job_id"], "succeeded")
    data = client.get("/gui/indexing-history").json()
    assert calls == ["one", None]
    assert len(data["jobs"]) == 2
    assert all(ws["last_success_at"] for ws in data["workspaces"])
    assert all(job["duration_seconds"] is not None for job in data["jobs"])


def test_failed_job_is_visible(config: Config, monkeypatch: pytest.MonkeyPatch):
    def fail(_config, *, workspace_id=None):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr("rag.indexer.run.run_index", fail)
    client = client_for(create_api_app(config))
    response = post(client, "one")
    assert response.status_code == 202
    wait_for_job(config, response.json()["job_id"], "failed")
    job = client.get("/gui/indexing-history").json()["jobs"][0]
    assert job["status"] == "failed"
    assert job["error"] == "embedding unavailable"


def test_failure_before_worker_claim_marks_job_failed(
    config: Config, monkeypatch: pytest.MonkeyPatch
):
    def run_job(config, **kwargs):
        if kwargs.get("wait") is False:
            return original_run_index_job(config, **kwargs)
        raise RuntimeError("workspace configuration changed")

    monkeypatch.setattr("rag.gui_api.run_index_job", run_job)
    client = client_for(create_api_app(config))
    response = post(client, "one")
    assert response.status_code == 202
    wait_for_job(config, response.json()["job_id"], "failed")
    assert client.get("/gui/indexing-history").json()["jobs"][0]["error"] == (
        "workspace configuration changed"
    )


def test_history_reads_legacy_status_and_expires_abandoned_job(config: Config):
    config.status_file_path.write_text(
        json.dumps({"workspace_ids": ["one"], "updated_at": "2025-01-02T03:04:05+00:00"}),
        encoding="utf-8",
    )
    job = original_run_index_job(config, workspace_id="one", wait=False)["job"]
    store = StatusStore(jobs_db_path(config))
    store.update(job["job_id"], lease_expires_at=time.time() - 1)
    history = client_for(create_api_app(config)).get("/gui/indexing-history").json()
    assert history["workspaces"][0]["last_success_at"] == 1735787045
    assert history["workspaces"][1]["last_success_at"] is None
    assert history["jobs"][0]["status"] == "failed"


def test_gui_request_validation_and_local_only(config: Config):
    client = client_for(create_api_app(config))
    assert post(client, "missing").status_code == 404
    assert post(client, "*").status_code == 400
    assert client.post("/gui/reindex", json={}).status_code == 403
    assert (
        client.post("/gui/reindex", json={}, headers={"origin": "http://evil.test"}).status_code
        == 403
    )
    assert (
        client.post(
            "/gui/reindex", content="bad", headers={"origin": "http://localhost:8000"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/gui/reindex",
            content="{",
            headers={"origin": "http://localhost:8000", "content-type": "application/json"},
        ).status_code
        == 400
    )
    assert client.get("/gui", headers={"host": "evil.test"}).status_code == 403
    remote = client_for(create_api_app(config), peer="192.0.2.1")
    assert remote.get("/gui").status_code in {401, 403}


def test_memory_mode_cannot_report_successful_reindex(config: Config):
    config.qdrant.mode = "memory"
    client = client_for(create_api_app(config))
    assert client.get("/gui/status").json()["reindex_available"] is False
    response = post(client, "one")
    assert response.status_code == 400
    assert "local or server" in response.json()["error"]


def test_restricted_token_cannot_use_dashboard(config: Config):
    config.mcp.auth.require_auth_always = True
    config.mcp.auth.tokens = [{"name": "limited", "token": "test-token", "workspaces": ["one"]}]
    client = client_for(create_api_app(config))
    assert client.get("/gui").status_code == 401
    headers = {"authorization": "Bearer test-token"}
    assert client.get("/gui", headers=headers).status_code == 403
    assert client.get("/gui/indexing-history", headers=headers).status_code == 403
    assert (
        client.post(
            "/gui/reindex",
            headers={**headers, "origin": "http://localhost:8000"},
            json={"workspace_id": "one"},
        ).status_code
        == 403
    )


def test_real_local_index_with_open_server_store(config: Config, tmp_path: Path, monkeypatch):
    class FakeEmbedder:
        def __init__(self, _config):
            pass

        def health_check(self):
            return True, "ok"

        def embed_texts(self, texts, *, for_query=False):
            return [[1.0, 0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr("rag.indexer.run.EmbeddingClient", FakeEmbedder)
    config.qdrant.mode = "local"
    config.qdrant.local_path = str(tmp_path / "qdrant")
    (tmp_path / "one" / "doc.md").write_text("# One\nOriginal", encoding="utf-8")
    (tmp_path / "two" / "doc.md").write_text("# Two\nKeep me", encoding="utf-8")
    runtime = RagRuntime(config)
    store = runtime.get_store()
    client = client_for(create_api_app(config))

    def run_job(workspace_id):
        deadline = time.monotonic() + 5
        while True:
            response = post(client, workspace_id)
            if response.status_code != 409 or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        assert response.status_code == 202
        wait_for_job(config, response.json()["job_id"], "succeeded")

    try:
        run_job(None)
        first_generation = store.collection
        assert store.count() == 2
        run_job(None)
        assert store.collection != first_generation
        assert store.count() == 2
        (tmp_path / "one" / "doc.md").write_text("# One\nUpdated", encoding="utf-8")
        run_job("one")
        points, _ = store.client.scroll(
            collection_name=store.collection, limit=100, with_payload=True
        )
        contents = {point.payload["workspace_id"]: point.payload["content"] for point in points}
        assert "Updated" in contents["one"]
        assert "Keep me" in contents["two"]
        status = client.get("/gui/status").json()
        assert status["index"]["points_count"] == 2
        assert all(
            ws["last_success_at"] for ws in client.get("/gui/indexing-history").json()["workspaces"]
        )

        class FailingEmbedder(FakeEmbedder):
            def __init__(self, _config):
                self.calls = 0

            def embed_texts(self, texts, *, for_query=False):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("embedding failed")
                return super().embed_texts(texts, for_query=for_query)

        monkeypatch.setattr("rag.indexer.run.EmbeddingClient", FailingEmbedder)
        from rag.indexer.run import run_index

        with pytest.raises(RuntimeError, match="embedding failed"):
            run_index(config, workspace_id="one")
        assert store.count() == 2
    finally:
        runtime.close()
