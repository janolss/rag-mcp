"""Canonical path checks, symlink policy, size limits and secret denylist."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SECRET_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "service-account.json",
        "id_rsa",
        "id_ed25519",
        "id_dsa",
        "id_ecdsa",
    }
)

DEFAULT_SECRET_SUFFIXES = frozenset(
    {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".jks",
    }
)

DEFAULT_ALLOWED_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".ejs",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".rst",
        ".csv",
    }
)


class SecurePathError(PermissionError):
    """Raised when a path violates the ingestion security policy."""


@dataclass(frozen=True)
class PathSecurityPolicy:
    """Policy applied before reading files for indexing."""

    allow_symlinks: bool = False
    max_file_bytes: int = 2_000_000
    allowed_suffixes: frozenset[str] = DEFAULT_ALLOWED_SUFFIXES
    secret_names: frozenset[str] = DEFAULT_SECRET_NAMES
    secret_suffixes: frozenset[str] = DEFAULT_SECRET_SUFFIXES
    registered_roots: tuple[str, ...] = field(default_factory=tuple)

    def with_roots(self, roots: list[str] | tuple[str, ...]) -> PathSecurityPolicy:
        return PathSecurityPolicy(
            allow_symlinks=self.allow_symlinks,
            max_file_bytes=self.max_file_bytes,
            allowed_suffixes=self.allowed_suffixes,
            secret_names=self.secret_names,
            secret_suffixes=self.secret_suffixes,
            registered_roots=tuple(str(Path(root).resolve()) for root in roots),
        )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_within_roots(
    path: Path | str,
    roots: list[str | Path] | tuple[str | Path, ...],
    *,
    policy: PathSecurityPolicy | None = None,
) -> Path:
    """
    Resolve ``path`` and ensure it stays inside one registered root.

    Returns the canonical path on success. Never logs file contents.
    """
    active = policy or PathSecurityPolicy()
    candidate = Path(path)
    resolved_roots = [Path(root).resolve() for root in roots]
    if not resolved_roots:
        raise SecurePathError("no registered roots configured")

    if candidate.is_symlink() and not active.allow_symlinks:
        raise SecurePathError(f"symlinks are not allowed: {candidate}")

    try:
        canonical = candidate.resolve(strict=False)
    except OSError as exc:
        raise SecurePathError(f"unable to resolve path: {candidate}") from exc

    if not any(_is_relative_to(canonical, root) for root in resolved_roots):
        raise SecurePathError(f"path escapes registered roots: {canonical}")

    name = canonical.name.lower()
    suffix = canonical.suffix.lower()
    if name in active.secret_names or suffix in active.secret_suffixes:
        raise SecurePathError(f"refusing to index secret-like file: {canonical.name}")

    if active.allowed_suffixes and suffix and suffix not in active.allowed_suffixes:
        raise SecurePathError(f"file suffix not allowed: {canonical.name}")

    if canonical.exists() and canonical.is_file():
        size = canonical.stat().st_size
        if size > active.max_file_bytes:
            raise SecurePathError(
                f"file exceeds max size ({size} > {active.max_file_bytes}): {canonical.name}"
            )

    return canonical


def safe_read_text(
    path: Path, *, policy: PathSecurityPolicy, roots: list[Path] | tuple[Path, ...]
) -> str:
    """Validate then read UTF-8 text without logging contents."""
    canonical = assert_within_roots(path, roots, policy=policy)
    return canonical.read_text(encoding="utf-8", errors="replace")


def filter_secure_files(
    files: list[Path],
    *,
    roots: list[Path] | tuple[Path, ...],
    policy: PathSecurityPolicy,
) -> list[Path]:
    """Keep only files that pass the security policy; log denials without content."""
    kept: list[Path] = []
    for path in files:
        try:
            kept.append(assert_within_roots(path, roots, policy=policy))
        except SecurePathError as exc:
            logger.warning("Skipping unsafe path during ingestion: %s", exc)
    return kept
