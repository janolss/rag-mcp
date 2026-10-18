"""Shared application-service errors."""

from __future__ import annotations


class ServiceError(Exception):
    """Base error for service-layer failures."""


class ForbiddenError(ServiceError):
    """Principal is not allowed to access the requested resource."""


class NotFoundError(ServiceError):
    """Requested workspace, source, or document does not exist."""


class ValidationError(ServiceError):
    """Invalid arguments for a service call."""


class WorkspaceRequiredError(ValidationError):
    """Raised when multi-workspace mode needs an explicit workspace_id."""


class AmbiguousWorkspaceError(ValidationError):
    """Multiple workspaces match a path at the same longest-prefix depth."""

    def __init__(self, message: str, *, path: str, candidates: list[dict]):
        super().__init__(message)
        self.path = path
        self.candidates = candidates
