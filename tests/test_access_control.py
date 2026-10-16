"""Network access and workspace authorization tests (Phase 16)."""

from __future__ import annotations

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
from rag.security.access import (
    AccessDenied,
    AccessPolicy,
    Principal,
    assert_bind_allowed,
    authorize_workspace,
    hash_token,
)
from starlette.testclient import TestClient


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
    config = Config(
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
            host="0.0.0.0",
            auth=McpAuthConfig(tokens=[{"name": "ops", "token_hash": digest, "workspaces": ["*"]}]),
        ),
    )
    client = TestClient(create_api_app(config))
    denied = client.get("/api/v1/workspaces")
    assert denied.status_code == 401
    ok = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer good"},
    )
    assert ok.status_code == 200


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
