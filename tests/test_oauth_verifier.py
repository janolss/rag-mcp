"""OIDC/JWT resource-server verifier and OAuth HTTP challenges."""

from __future__ import annotations

import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rag.config import (
    Config,
    EmbeddingConfig,
    IndexConfig,
    McpAuthConfig,
    McpConfig,
    McpOAuthConfig,
    QdrantConfig,
    SearchConfig,
)
from rag.http_api import create_api_app
from rag.mcp_http import _attach_http_routes
from rag.mcp_server import create_mcp_server
from rag.security.access import assert_bind_allowed, hash_token
from rag.security.oauth import (
    CompositeTokenVerifier,
    build_access_policy,
    build_auth_settings,
)
from starlette.testclient import TestClient
from tests.workspace_fixtures import with_workspace_manifest


def _rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, key


@pytest.fixture
def rsa_keys(monkeypatch: pytest.MonkeyPatch):
    private_pem, key = _rsa_pair()

    class KeyObj:
        def __init__(self, k):
            self.key = k

    public_key = key.public_key()

    def fake_jwks(self, oauth):
        return type(
            "C",
            (),
            {"get_signing_key_from_jwt": lambda _self, _t: KeyObj(public_key)},
        )()

    monkeypatch.setattr(CompositeTokenVerifier, "_jwks_client", fake_jwks)
    return private_pem, "https://issuer.example/tenant", "api://rag-mcp"


def _oauth_config(
    tmp_path: Path,
    *,
    host: str = "0.0.0.0",
    tokens: list[dict] | None = None,
    issuer: str = "https://issuer.example/tenant",
    audience: str = "api://rag-mcp",
) -> Config:
    return with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="oauth"),
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
                transport="streamable-http",
                auth=McpAuthConfig(
                    tokens=list(tokens or []),
                    oauth=McpOAuthConfig(
                        enabled=True,
                        issuer_url=issuer,
                        audience=audience,
                        resource_server_url="http://127.0.0.1:8000/mcp",
                        jwks_uri=f"{issuer}/keys",
                    ),
                ),
            ),
        ),
        tmp_path,
    )


def test_public_bind_allows_oauth_without_tokens(tmp_path: Path):
    config = _oauth_config(tmp_path, tokens=[])
    policy = build_access_policy(config)
    assert policy.has_auth_profile()
    assert_bind_allowed("0.0.0.0", policy, transport="http")


def test_build_auth_settings_requires_audience(tmp_path: Path):
    config = _oauth_config(tmp_path)
    config.mcp.auth.oauth.audience = ""
    with pytest.raises(ValueError, match="audience"):
        build_auth_settings(config)


def test_static_token_still_works_with_oauth(tmp_path: Path, rsa_keys):
    _private_pem, issuer, audience = rsa_keys
    digest = hash_token("static-secret")
    config = _oauth_config(
        tmp_path,
        tokens=[{"name": "ci", "token_hash": digest, "workspaces": ["*"]}],
        issuer=issuer,
        audience=audience,
    )
    client = TestClient(create_api_app(config))
    denied = client.get("/api/v1/workspaces")
    assert denied.status_code == 401
    assert "WWW-Authenticate" in denied.headers
    assert "resource_metadata" in denied.headers["WWW-Authenticate"]
    ok = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer static-secret"},
    )
    assert ok.status_code == 200


def test_jwt_audience_and_issuer(tmp_path: Path, rsa_keys):
    private_pem, issuer, audience = rsa_keys
    config = _oauth_config(tmp_path, issuer=issuer, audience=audience)
    verifier = CompositeTokenVerifier(config)

    good = jwt.encode(
        {
            "sub": "user-1",
            "oid": "oid-1",
            "iss": issuer,
            "aud": audience,
            "exp": int(time.time()) + 3600,
        },
        private_pem,
        algorithm="RS256",
    )
    access = verifier.verify_token_sync(good)
    assert access is not None
    assert access.subject == "oid-1"

    bad_aud = jwt.encode(
        {
            "sub": "user-1",
            "iss": issuer,
            "aud": "wrong",
            "exp": int(time.time()) + 3600,
        },
        private_pem,
        algorithm="RS256",
    )
    assert verifier.verify_token_sync(bad_aud) is None

    client = TestClient(create_api_app(config))
    ok = client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {good}"})
    assert ok.status_code == 200
    denied = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {bad_aud}"},
    )
    assert denied.status_code == 401


def test_mcp_exposes_protected_resource_metadata(tmp_path: Path, rsa_keys):
    _private_pem, issuer, audience = rsa_keys
    config = _oauth_config(tmp_path, issuer=issuer, audience=audience)
    mcp = create_mcp_server(config)
    app = mcp.streamable_http_app(
        host=config.mcp.host,
        streamable_http_path="/mcp",
        stateless_http=True,
    )
    _attach_http_routes(app, config)
    client = TestClient(app, raise_server_exceptions=False)
    meta = client.get("/.well-known/oauth-protected-resource/mcp")
    assert meta.status_code == 200
    body = meta.json()
    assert "authorization_servers" in body
    resp = client.post("/mcp")
    assert resp.status_code == 401
    www = resp.headers.get("www-authenticate", "")
    assert "resource_metadata" in www or "Bearer" in www


def test_auth_fail_is_logged(tmp_path: Path, rsa_keys, caplog: pytest.LogCaptureFixture):
    import logging

    _private_pem, issuer, audience = rsa_keys
    config = _oauth_config(tmp_path, issuer=issuer, audience=audience)
    client = TestClient(create_api_app(config))
    with caplog.at_level(logging.WARNING, logger="rag.security.http_auth"):
        client.get("/api/v1/workspaces")
    assert any("auth_fail" in r.message and "missing_bearer" in r.message for r in caplog.records)
    assert not any("Bearer ey" in r.message for r in caplog.records)
