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
