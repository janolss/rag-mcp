"""Thin service protocols shared by MCP and HTTP adapters.

These contracts define the application service boundaries. This module
introduces the protocols only; concrete implementations live elsewhere.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceService(Protocol):
    """List and describe registered workspaces."""

    def list_workspaces(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return workspaces visible to the caller."""

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Return detailed workspace metadata for a stable workspace ID."""

    def resolve_workspace(self, path: str) -> dict[str, Any]:
        """Map a filesystem path to a workspace via longest-prefix source root."""


@runtime_checkable
class SourceService(Protocol):
    """List sources belonging to a workspace."""

    def list_sources(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return sources for the given workspace."""


@runtime_checkable
class SearchService(Protocol):
    """Search indexed content with workspace isolation."""

    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        search_mode: str = "hybrid",
        source_ids: list[str] | None = None,
        document_types: list[str] | None = None,
        limit: int | None = None,
        scope: str = "workspace",
    ) -> list[dict[str, Any]]:
        """Return ranked search hits for a workspace-scoped query."""


@runtime_checkable
class DocumentService(Protocol):
    """Fetch original document content from registered sources."""

    def get_document(
        self,
        *,
        workspace_id: str,
        source_id: str,
        document_id: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Return document content and metadata for a registered document."""


@runtime_checkable
class StatusService(Protocol):
    """Expose index and job status."""

    def get_index_status(
        self,
        *,
        workspace_id: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Return indexing status for optional workspace/source filters."""
