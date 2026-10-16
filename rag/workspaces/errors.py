"""Manifest and workspace configuration errors."""

from __future__ import annotations


class ManifestError(ValueError):
    """Base error for workspace manifest problems."""


class ManifestValidationError(ManifestError):
    """Raised when a manifest fails schema or semantic validation."""

    def __init__(self, message: str, *, path: str | None = None):
        self.path = path
        prefix = f"{path}: " if path else ""
        super().__init__(f"{prefix}{message}")


class ManifestNotFoundError(ManifestError):
    """Raised when a configured manifest path does not exist."""
