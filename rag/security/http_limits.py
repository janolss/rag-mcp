"""HTTP request body size and per-IP rate limits."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from starlette.responses import JSONResponse

from rag.security.access import is_loopback_host
from rag.security.http_auth import _looks_like_ip


class MaxBodyMiddleware:
    """Reject requests whose Content-Length exceeds ``max_body_bytes`` (0 disables)."""

    def __init__(self, app: Any, *, max_body_bytes: int = 1_048_576):
        self.app = app
        self.max_body_bytes = max(0, int(max_body_bytes))

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or self.max_body_bytes <= 0:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        raw_len = headers.get("content-length")
        if raw_len is not None:
            try:
                length = int(raw_len)
            except ValueError:
                length = -1
            if length > self.max_body_bytes:
                response = JSONResponse(
                    {"error": "request body too large", "code": "body_too_large"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """
    Sliding-window rate limit per client IP.

    Inactive when ``rate_limit_per_minute`` is 0, or when the peer (or bind host
    as fallback) is loopback and ``require_auth_always`` is false.
    """

    def __init__(
        self,
        app: Any,
        *,
        rate_limit_per_minute: int = 120,
        bind_host: str = "127.0.0.1",
        require_auth_always: bool = False,
    ):
        self.app = app
        self.limit = max(0, int(rate_limit_per_minute))
        self.bind_host = bind_host
        self.require_auth_always = require_auth_always
        self._window_s = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _client_ip(self, scope: dict) -> str:
        client = scope.get("client")
        if client and client[0]:
            return str(client[0])
        return "unknown"

    def _limits_active(self, scope: dict) -> bool:
        if self.limit <= 0:
            return False
        if self.require_auth_always:
            return True
        peer = self._client_ip(scope)
        if peer != "unknown" and _looks_like_ip(peer):
            return not is_loopback_host(peer)
        return not is_loopback_host(self.bind_host)

    def _allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_s
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not self._limits_active(scope):
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path == "/health":
            await self.app(scope, receive, send)
            return

        if not self._allow(self._client_ip(scope)):
            response = JSONResponse(
                {"error": "rate limit exceeded", "code": "rate_limited"},
                status_code=429,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
