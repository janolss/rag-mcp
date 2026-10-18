"""HTTP bearer-token authentication middleware."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from starlette.responses import JSONResponse

from rag.security.access import (
    LOCAL_ANONYMOUS,
    AccessPolicy,
    Principal,
    is_loopback_host,
)

logger = logging.getLogger(__name__)

_principal: ContextVar[Principal | None] = ContextVar("rag_principal", default=None)

# Paths owned by the MCP SDK auth stack when OAuth resource-server mode is on.
_SDK_AUTH_PREFIXES = ("/mcp", "/sse", "/messages")


def get_principal() -> Principal | None:
    return _principal.get()


def set_principal(principal: Principal | None) -> None:
    _principal.set(principal)


def require_principal(*, allow_anonymous: bool = True) -> Principal:
    principal = get_principal()
    if principal is None:
        if allow_anonymous:
            return LOCAL_ANONYMOUS
        raise PermissionError("authentication required")
    return principal


def _client_host(scope: dict) -> str | None:
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return None


def _looks_like_ip(host: str) -> bool:
    text = (host or "").strip()
    if not text:
        return False
    if text.count(".") == 3 and all(p.isdigit() for p in text.split(".")):
        return True
    return ":" in text


def _is_sdk_owned_path(path: str) -> bool:
    if path.startswith("/.well-known/"):
        return True
    for prefix in _SDK_AUTH_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


class BearerAuthMiddleware:
    """
    Resolve Authorization: Bearer tokens into a Principal.

    Anonymous access is allowed only when the peer (or bind host as fallback) is
    loopback, ``require_auth_always`` is false, and no bearer was sent.
    Non-loopback requests without a valid token are rejected with 401 when an
    auth profile exists (or always when require_auth_for_public_bind is set).

    When ``skip_sdk_paths`` is true (OAuth resource-server mode), MCP and
    well-known paths are left to the MCP SDK auth middleware.
    """

    def __init__(
        self,
        app: Any,
        policy: AccessPolicy,
        *,
        bind_host: str = "127.0.0.1",
        require_auth_always: bool = False,
        token_verifier: Any | None = None,
        resource_metadata_url: str | None = None,
        skip_sdk_paths: bool = False,
    ):
        self.app = app
        self.policy = policy
        self.bind_host = bind_host
        self.require_auth_always = require_auth_always
        self.token_verifier = token_verifier
        self.resource_metadata_url = resource_metadata_url
        self.skip_sdk_paths = skip_sdk_paths

    def _anonymous_allowed(self, scope: dict) -> bool:
        if self.require_auth_always:
            return False
        peer = _client_host(scope)
        if peer and _looks_like_ip(peer):
            return is_loopback_host(peer)
        # Missing peer or non-IP ASGI clients (e.g. Starlette TestClient): use bind host.
        return is_loopback_host(self.bind_host)

    def _unauthorized(self, scope: dict, *, reason: str) -> JSONResponse:
        peer = _client_host(scope) or "unknown"
        path = scope.get("path") or ""
        logger.warning(
            "auth_fail peer=%s path=%s reason=%s",
            peer,
            path,
            reason,
        )
        headers: dict[str, str] = {}
        if self.resource_metadata_url:
            headers["WWW-Authenticate"] = (
                f'Bearer error="invalid_token", resource_metadata="{self.resource_metadata_url}"'
            )
        return JSONResponse(
            {"error": "unauthorized", "code": "unauthorized"},
            status_code=401,
            headers=headers,
        )

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path == "/health" or path.startswith("/.well-known/"):
            token = _principal.set(LOCAL_ANONYMOUS)
            try:
                await self.app(scope, receive, send)
            finally:
                _principal.reset(token)
            return

        if self.skip_sdk_paths and _is_sdk_owned_path(path):
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        bearer = None
        if auth.lower().startswith("bearer "):
            bearer = auth[7:].strip()

        principal: Principal | None = None
        if bearer:
            if self.token_verifier is not None:
                access = self.token_verifier.verify_token_sync(bearer)
                principal = get_principal() if access is not None else None
                if access is not None and principal is None:
                    principal = Principal(
                        subject=access.subject or access.client_id,
                        anonymous=False,
                    )
                    set_principal(principal)
            else:
                principal = self.policy.authenticate(bearer)

        if principal is None:
            if (self._anonymous_allowed(scope) and not bearer) or (
                not self.policy.has_auth_profile() and self._anonymous_allowed(scope)
            ):
                principal = LOCAL_ANONYMOUS
            else:
                reason = "invalid_token" if bearer else "missing_bearer"
                response = self._unauthorized(scope, reason=reason)
                await response(scope, receive, send)
                return

        logger.debug(
            "auth_ok subject=%s path=%s anonymous=%s",
            principal.subject,
            path,
            principal.anonymous,
        )
        token = _principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(token)
