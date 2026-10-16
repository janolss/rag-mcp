"""In-memory registry of workspaces with stable ID lookup."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from rag.config import Config
from rag.domain.models import Workspace
from rag.workspaces.legacy import workspace_from_config


class WorkspaceNotFoundError(KeyError):
    """Raised when a workspace ID is not registered."""


class DuplicateWorkspaceError(ValueError):
    """Raised when registering a workspace ID that already exists."""


class WorkspaceRegistry:
    """Thread-local style immutable snapshot registry for workspaces."""

    def __init__(self, workspaces: Sequence[Workspace] | None = None):
        self._by_id: dict[str, Workspace] = {}
        for workspace in workspaces or ():
            self.register(workspace)

    @classmethod
    def from_config(cls, config: Config) -> WorkspaceRegistry:
        """Create a registry containing the legacy default workspace."""
        return cls([workspace_from_config(config)])

    def register(self, workspace: Workspace) -> None:
        workspace_id = (workspace.id or "").strip()
        if not workspace_id:
            raise ValueError("workspace.id cannot be empty")
        if workspace_id in self._by_id:
            raise DuplicateWorkspaceError(f"workspace already registered: {workspace_id}")
        self._by_id[workspace_id] = workspace

    def replace_all(self, workspaces: Iterable[Workspace]) -> None:
        """Atomically replace the registry contents."""
        next_map: dict[str, Workspace] = {}
        for workspace in workspaces:
            workspace_id = (workspace.id or "").strip()
            if not workspace_id:
                raise ValueError("workspace.id cannot be empty")
            if workspace_id in next_map:
                raise DuplicateWorkspaceError(f"duplicate workspace id in reload: {workspace_id}")
            next_map[workspace_id] = workspace
        self._by_id = next_map

    def get(self, workspace_id: str) -> Workspace:
        key = (workspace_id or "").strip()
        try:
            return self._by_id[key]
        except KeyError as exc:
            raise WorkspaceNotFoundError(f"unknown workspace: {workspace_id!r}") from exc

    def list(
        self,
        *,
        query: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> list[Workspace]:
        items = list(self._by_id.values())
        if tags:
            wanted = {t.strip().lower() for t in tags if t and t.strip()}
            items = [ws for ws in items if wanted.issubset({t.lower() for t in ws.tags})]
        if query:
            q = query.strip().lower()
            items = [
                ws
                for ws in items
                if q in ws.id.lower() or q in ws.name.lower() or q in (ws.description or "").lower()
            ]
        return sorted(items, key=lambda ws: ws.id)

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, workspace_id: object) -> bool:
        return isinstance(workspace_id, str) and workspace_id in self._by_id
