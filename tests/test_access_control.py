"""Network access and workspace authorization tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rag.config import (
    Config,
    EmbeddingConfig,
    IndexConfig,
    McpAuthConfig,
    McpConfig,
    QdrantConfig,
    SearchConfig,
)
from rag.http_api import create_api_app
from rag.mcp_http import _attach_http_routes
from rag.mcp_server import create_mcp_server
from rag.security.access import (
    AccessDenied,
    AccessPolicy,
    Principal,
    assert_bind_allowed,
    authorize_workspace,
    hash_token,
)
from rag.security.http_auth import set_principal
from rag.services import ServiceApp, ServiceError
from starlette.testclient import TestClient


def _base_config(
    tmp_path: Path,
    *,
    host: str = "127.0.0.1",
    tokens: list[dict] | None = None,
) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="acl"),
        index=IndexConfig(
            repo_root=str(tmp_path),
            status_file=str(tmp_path / "status.json"),
            knowledge=[],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
        mcp=McpConfig(
            host=host,
            auth=McpAuthConfig(tokens=list(tokens or [])),
        ),
    )


def _production_http_app(config: Config):
    mcp = create_mcp_server(config)
    app = mcp.streamable_http_app(
        host=config.mcp.host,
        streamable_http_path="/mcp",
        stateless_http=True,
    )
    _attach_http_routes(app, config)
    return app


def test_public_bind_requires_auth_profile():
    policy = AccessPolicy(tokens=())
    with pytest.raises(RuntimeError, match="non-loopback"):
        assert_bind_allowed("0.0.0.0", policy, transport="http")
    assert_bind_allowed("127.0.0.1", policy, transport="http")
    assert_bind_allowed("0.0.0.0", policy, transport="stdio")


def test_token_auth_and_workspace_allowlist():
    digest = hash_token("secret-token")
    policy = AccessPolicy.from_mapping(
        {
            "tokens": [
                {
                    "name": "ci",
                    "token_hash": digest,
                    "workspaces": ["alpha"],
                    "sources": ["knowledge"],
                }
            ]
        }
    )
    principal = policy.authenticate("secret-token")
    assert principal is not None
    assert principal.subject == "ci"
    authorize_workspace(principal, "alpha")
    with pytest.raises(AccessDenied):
        authorize_workspace(principal, "beta")
    assert policy.authenticate("wrong") is None


def test_rest_bearer_required_on_public_host(tmp_path: Path):
    digest = hash_token("good")
    config = _base_config(
        tmp_path,
        host="0.0.0.0",
        tokens=[{"name": "ops", "token_hash": digest, "workspaces": ["*"]}],
    )
    client = TestClient(create_api_app(config))
    denied = client.get("/api/v1/workspaces")
    assert denied.status_code == 401
    ok = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer good"},
    )
    assert ok.status_code == 200


def test_production_http_requires_bearer_on_rest_and_mcp(tmp_path: Path):
    digest = hash_token("prod-token")
    config = _base_config(
        tmp_path,
        host="0.0.0.0",
        tokens=[{"name": "ops", "token_hash": digest, "workspaces": ["*"]}],
    )
    client = TestClient(_production_http_app(config), raise_server_exceptions=False)
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.post("/mcp").status_code == 401
    ok = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer prod-token"},
    )
    assert ok.status_code == 200
    health = client.get("/health")
    assert health.status_code == 200


def test_loopback_allows_anonymous_rest(tmp_path: Path):
    config = _base_config(tmp_path, host="127.0.0.1", tokens=[])
    client = TestClient(create_api_app(config))
    assert client.get("/api/v1/workspaces").status_code == 200


def test_search_documents_status_respect_workspace_allowlist(tmp_path: Path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# Hello\n", encoding="utf-8")
    config = Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="acl_svc"),
        index=IndexConfig(
            repo_root=str(repo),
            status_file=str(tmp_path / "status.json"),
            knowledge=["docs/**/*.md"],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )
    services = ServiceApp(config)
    restricted = Principal(
        subject="reader",
        anonymous=False,
        workspace_allowlist=frozenset({"alpha"}),
        source_allowlist=frozenset({"knowledge"}),
    )
    set_principal(restricted)
    try:
        with pytest.raises(ServiceError, match="cannot access"):
            services.search.search(workspace_id="default", query="hello")
        with pytest.raises(ServiceError, match="cannot access"):
            services.documents.get_document(
                workspace_id="default",
                source_id="knowledge",
                document_id="docs/a.md",
            )
        with pytest.raises(ServiceError, match="cannot access"):
            services.status.get_index_status(workspace_id="default")
    finally:
        set_principal(None)

    allowed = Principal(
        subject="reader",
        anonymous=False,
        workspace_allowlist=frozenset({"default"}),
        source_allowlist=frozenset({"knowledge"}),
    )
    set_principal(allowed)
    try:
        status = services.status.get_index_status(workspace_id="default")
        assert status["workspace_id"] == "default"
        doc = services.documents.get_document(
            workspace_id="default",
            source_id="knowledge",
            document_id="docs/a.md",
        )
        assert "Hello" in doc["content"]
        with pytest.raises(ServiceError, match="cannot access"):
            services.search.search(
                workspace_id="default",
                query="hello",
                source_ids=["code"],
            )
    finally:
        set_principal(None)


def test_rest_search_forbidden_for_disallowed_workspace(tmp_path: Path):
    digest = hash_token("scoped")
    config = _base_config(
        tmp_path,
        host="0.0.0.0",
        tokens=[
            {
                "name": "scoped",
                "token_hash": digest,
                "workspaces": ["alpha"],
                "sources": ["*"],
            }
        ],
    )
    client = TestClient(create_api_app(config))
    resp = client.post(
        "/api/v1/search",
        headers={"Authorization": "Bearer scoped"},
        content=json.dumps({"query": "x", "workspace_id": "default"}),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_principal_filter_parity():
    principal = Principal(
        subject="reader",
        workspace_allowlist=frozenset({"default"}),
        source_allowlist=frozenset({"knowledge"}),
    )
    assert principal.allows_workspace("default")
    assert not principal.allows_workspace("other")
    assert principal.allows_source("knowledge")
    assert not principal.allows_source("code")
