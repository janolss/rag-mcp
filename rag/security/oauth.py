"""OIDC/JWT resource-server verification and MCP AuthSettings helpers."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urljoin

import httpx
import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from rag.config import Config, McpOAuthConfig, mcp_public_url
from rag.security.access import AccessPolicy, Principal
from rag.security.http_auth import set_principal

logger = logging.getLogger(__name__)

_JWKS_CACHE: dict[str, tuple[float, PyJWKClient]] = {}
_JWKS_LOCK = threading.Lock()
_JWKS_TTL_S = 3600.0


def oauth_enabled(config: Config) -> bool:
    oauth = config.mcp.auth.oauth
    return bool(oauth and oauth.enabled)


def resource_server_url(config: Config) -> str:
    oauth = config.mcp.auth.oauth
    explicit = (oauth.resource_server_url if oauth else "") or ""
    if explicit.strip():
        return explicit.strip().rstrip("/")
    public = mcp_public_url(config)
    if public:
        return public.rstrip("/")
    host = config.mcp.host or "127.0.0.1"
    port = int(config.mcp.port)
    return f"http://{host}:{port}/mcp"


def protected_resource_metadata_url(config: Config) -> str:
    """RFC 9728 well-known URL derived from the MCP resource URL."""
    resource = resource_server_url(config)
    # https://host/mcp → https://host/.well-known/oauth-protected-resource/mcp
    if "://" not in resource:
        return f"/.well-known/oauth-protected-resource{resource}"
    scheme, rest = resource.split("://", 1)
    host, _, path = rest.partition("/")
    path = f"/{path}" if path else ""
    return f"{scheme}://{host}/.well-known/oauth-protected-resource{path}"


def build_auth_settings(config: Config) -> AuthSettings | None:
    if not oauth_enabled(config):
        return None
    oauth = config.mcp.auth.oauth
    assert oauth is not None
    issuer = (oauth.issuer_url or "").strip()
    if not issuer:
        raise ValueError("mcp.auth.oauth.issuer_url is required when oauth.enabled is true")
    audience = (oauth.audience or "").strip()
    if not audience:
        raise ValueError("mcp.auth.oauth.audience is required when oauth.enabled is true")
    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer if issuer.endswith("/") else f"{issuer}/"),
        resource_server_url=AnyHttpUrl(resource_server_url(config)),
        required_scopes=list(oauth.required_scopes) or None,
        validate_token_resource=False,
    )


def build_access_policy(config: Config) -> AccessPolicy:
    return AccessPolicy.from_mapping(
        {
            "tokens": list(config.mcp.auth.tokens),
            "require_auth_for_public_bind": config.mcp.auth.require_auth_for_public_bind,
            "require_auth_always": config.mcp.auth.require_auth_always,
            "oauth_enabled": oauth_enabled(config),
        }
    )


class CompositeTokenVerifier:
    """Verify static API tokens or OIDC JWTs; set Principal on success."""

    def __init__(self, config: Config, policy: AccessPolicy | None = None):
        self.config = config
        self.policy = policy or build_access_policy(config)
        self.oauth = config.mcp.auth.oauth
        self.resource_url = resource_server_url(config)

    async def verify_token(self, token: str) -> AccessToken | None:
        return self.verify_token_sync(token)

    def verify_token_sync(self, token: str) -> AccessToken | None:
        raw = (token or "").strip()
        if not raw:
            return None

        principal = self.policy.authenticate(raw)
        if principal is not None:
            set_principal(principal)
            return AccessToken(
                token=raw,
                client_id=principal.subject,
                scopes=[],
                subject=principal.subject,
                resource=self.resource_url,
            )

        if self.oauth and self.oauth.enabled:
            claims = self._verify_jwt(raw, self.oauth)
            if claims is not None:
                subject = str(claims.get("oid") or claims.get("sub") or "jwt")
                principal = Principal(subject=subject, anonymous=False)
                set_principal(principal)
                scopes = _scopes_from_claims(claims)
                return AccessToken(
                    token=raw,
                    client_id=str(claims.get("azp") or claims.get("appid") or subject),
                    scopes=scopes,
                    expires_at=_as_int(claims.get("exp")),
                    subject=subject,
                    resource=self.resource_url,
                    claims=dict(claims),
                )
        return None

    def _verify_jwt(self, token: str, oauth: McpOAuthConfig) -> dict[str, Any] | None:
        issuer = (oauth.issuer_url or "").strip().rstrip("/")
        audience = (oauth.audience or "").strip()
        if not issuer or not audience:
            return None
        try:
            jwks_client = self._jwks_client(oauth)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                audience=audience,
                issuer=[issuer, f"{issuer}/"],
                options={"require": ["exp", "iss", "aud"]},
            )
        except Exception as exc:
            logger.debug("JWT verification failed: %s", type(exc).__name__)
            return None

        required = list(oauth.required_scopes or [])
        if required:
            token_scopes = set(_scopes_from_claims(claims))
            if not all(scope in token_scopes for scope in required):
                logger.debug("JWT missing required scopes")
                return None
        return claims

    def _jwks_client(self, oauth: McpOAuthConfig) -> PyJWKClient:
        jwks_uri = (oauth.jwks_uri or "").strip() or self._discover_jwks_uri(oauth)
        now = time.monotonic()
        with _JWKS_LOCK:
            cached = _JWKS_CACHE.get(jwks_uri)
            if cached and cached[0] > now:
                return cached[1]
            client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=int(_JWKS_TTL_S))
            _JWKS_CACHE[jwks_uri] = (now + _JWKS_TTL_S, client)
            return client

    def _discover_jwks_uri(self, oauth: McpOAuthConfig) -> str:
        issuer = (oauth.issuer_url or "").strip().rstrip("/")
        # Prefer OIDC discovery; fall back to common JWKS path.
        discovery = urljoin(f"{issuer}/", ".well-known/openid-configuration")
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(discovery)
                if resp.status_code < 400:
                    body = resp.json()
                    uri = body.get("jwks_uri")
                    if isinstance(uri, str) and uri.strip():
                        return uri.strip()
        except Exception:
            logger.debug("OIDC discovery failed for %s", issuer)
        return f"{issuer}/discovery/v2.0/keys"


def _scopes_from_claims(claims: dict[str, Any]) -> list[str]:
    scp = claims.get("scp")
    if isinstance(scp, str):
        return [p for p in scp.split() if p]
    if isinstance(scp, list):
        return [str(p) for p in scp if str(p).strip()]
    scope = claims.get("scope")
    if isinstance(scope, str):
        return [p for p in scope.split() if p]
    return []


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
