"""Workspace/source authorization for MCP and REST adapters."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any


class AccessDenied(PermissionError):
    """Principal is not allowed to access the requested workspace/source."""


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity (anonymous for loopback/stdio)."""

    subject: str
    anonymous: bool = False
    workspace_allowlist: frozenset[str] = field(default_factory=frozenset)
    source_allowlist: frozenset[str] = field(default_factory=frozenset)

    def allows_workspace(self, workspace_id: str) -> bool:
        if self.anonymous:
            return True
        if not self.workspace_allowlist:
            return True
        return workspace_id in self.workspace_allowlist or "*" in self.workspace_allowlist

    def allows_source(self, source_id: str) -> bool:
        if self.anonymous:
            return True
        if not self.source_allowlist:
            return True
        return source_id in self.source_allowlist or "*" in self.source_allowlist


LOCAL_ANONYMOUS = Principal(subject="local", anonymous=True)


@dataclass(frozen=True)
class TokenRecord:
    name: str
    token_hash: str
    workspace_allowlist: tuple[str, ...] = ()
    source_allowlist: tuple[str, ...] = ()


@dataclass
class AccessPolicy:
    """
    Auth profile.

    Loopback/stdio may use anonymous access unless ``require_auth_always`` is set.
    Non-loopback binds require at least one token when
    ``require_auth_for_public_bind`` is True (default).
    """

    tokens: tuple[TokenRecord, ...] = ()
    require_auth_for_public_bind: bool = True
    require_auth_always: bool = False
    oauth_enabled: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AccessPolicy:
        data = data or {}
        tokens: list[TokenRecord] = []
        for item in data.get("tokens") or []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("token") or item.get("secret") or "").strip()
            digest = str(item.get("token_hash") or "").strip()
            if raw and not digest:
                digest = hash_token(raw)
            if not digest:
                continue
            tokens.append(
                TokenRecord(
                    name=str(item.get("name") or "token"),
                    token_hash=digest,
                    workspace_allowlist=tuple(item.get("workspaces") or ()),
                    source_allowlist=tuple(item.get("sources") or ()),
                )
            )
        return cls(
            tokens=tuple(tokens),
            require_auth_for_public_bind=bool(data.get("require_auth_for_public_bind", True)),
            require_auth_always=bool(data.get("require_auth_always", False)),
            oauth_enabled=bool(data.get("oauth_enabled", False)),
        )

    def authenticate(self, bearer_token: str | None) -> Principal | None:
        if not bearer_token:
            return None
        digest = hash_token(bearer_token.strip())
        for record in self.tokens:
            if hmac.compare_digest(record.token_hash, digest):
                return Principal(
                    subject=record.name,
                    anonymous=False,
                    workspace_allowlist=frozenset(record.workspace_allowlist),
                    source_allowlist=frozenset(record.source_allowlist),
                )
        return None

    def has_auth_profile(self) -> bool:
        return bool(self.tokens) or self.oauth_enabled


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def assert_bind_allowed(host: str, policy: AccessPolicy, *, transport: str) -> None:
    """Refuse non-loopback HTTP binds without an auth profile."""
    if transport == "stdio":
        return
    if is_loopback_host(host):
        return
    if policy.require_auth_for_public_bind and not policy.has_auth_profile():
        raise RuntimeError(
            f"refusing to bind MCP/HTTP on non-loopback host {host!r} without an "
            "auth profile (configure mcp.auth.tokens and/or mcp.auth.oauth)"
        )


def authorize_workspace(principal: Principal, workspace_id: str) -> None:
    if not principal.allows_workspace(workspace_id):
        raise AccessDenied(
            f"principal {principal.subject!r} cannot access workspace {workspace_id!r}"
        )


def authorize_source(principal: Principal, source_id: str) -> None:
    if not principal.allows_source(source_id):
        raise AccessDenied(f"principal {principal.subject!r} cannot access source {source_id!r}")
