"""HTTP bearer-token authentication middleware."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.responses import JSONResponse

from rag.security.access import (
    LOCAL_ANONYMOUS,
    AccessPolicy,
    Principal,
    is_loopback_host,
)

_principal: ContextVar[Principal | None] = ContextVar("rag_principal", default=None)


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


class BearerAuthMiddleware:
    """
    Resolve Authorization: Bearer tokens into a Principal.

    Anonymous access is allowed only when the peer (or bind host as fallback) is
    loopback, ``require_auth_always`` is false, and no bearer was sent.
    Non-loopback requests without a valid token are rejected with 401 when an
    auth profile exists (or always when require_auth_for_public_bind is set).
    """

    def __init__(
        self,
        app: Any,
        policy: AccessPolicy,
        *,
        bind_host: str = "127.0.0.1",
        require_auth_always: bool = False,
    ):
        self.app = app
        self.policy = policy
        self.bind_host = bind_host
        self.require_auth_always = require_auth_always

    def _anonymous_allowed(self, scope: dict) -> bool:
        if self.require_auth_always:
            return False
        peer = _client_host(scope)
        if peer and _looks_like_ip(peer):
            return is_loopback_host(peer)
        # Missing peer or non-IP ASGI clients (e.g. Starlette TestClient): use bind host.
        return is_loopback_host(self.bind_host)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path == "/health":
            token = _principal.set(LOCAL_ANONYMOUS)
            try:
                await self.app(scope, receive, send)
            finally:
                _principal.reset(token)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        bearer = None
        if auth.lower().startswith("bearer "):
            bearer = auth[7:].strip()

        principal = self.policy.authenticate(bearer) if bearer else None

        if principal is None:
            if (self._anonymous_allowed(scope) and not bearer) or (
                not self.policy.has_auth_profile() and self._anonymous_allowed(scope)
            ):
                principal = LOCAL_ANONYMOUS
            else:
                response = JSONResponse(
                    {"error": "unauthorized", "code": "unauthorized"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return

        token = _principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(token)
