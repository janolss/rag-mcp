"""Validated workspace relationships and related-scope expansion."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rag.domain.models import Relationship, RelationshipType, Workspace
from rag.security.access import Principal
from rag.workspaces.registry import WorkspaceRegistry

ALLOWED_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    {
        "depends_on",
        "references",
        "implements",
        "documents",
        "tests",
        "shares_contract_with",
    }
)


class RelationshipValidationError(ValueError):
    """Invalid relationship declaration or expansion request."""


@dataclass(frozen=True)
class ExpandedTarget:
    workspace_id: str
    via: tuple[str, ...]
    relationship_types: tuple[str, ...]


class RelationshipRegistry:
    def __init__(self, workspaces: WorkspaceRegistry):
        self._workspaces = workspaces

    @classmethod
    def from_workspace_registry(cls, registry: WorkspaceRegistry) -> RelationshipRegistry:
        return cls(registry)

    def validate_workspace(self, workspace: Workspace) -> None:
        known = set(self._workspaces.ids())
        seen: set[tuple[str, str]] = set()
        for rel in workspace.relationships:
            self._validate_type(rel.type)
            if rel.target not in known:
                raise RelationshipValidationError(
                    f"unknown relationship target {rel.target!r} from {workspace.id!r}"
                )
            if rel.target == workspace.id:
                raise RelationshipValidationError(
                    f"relationship cannot target the same workspace {workspace.id!r}"
                )
            key = (rel.type, rel.target)
            if key in seen:
                raise RelationshipValidationError(
                    f"duplicate relationship {rel.type!r} -> {rel.target!r} on {workspace.id!r}"
                )
            seen.add(key)

    def validate_all(self) -> None:
        for workspace in self._workspaces.list():
            self.validate_workspace(workspace)

    def expand_related(
        self,
        workspace_id: str,
        *,
        principal: Principal | None = None,
        max_depth: int = 1,
    ) -> list[ExpandedTarget]:
        """
        Expand authorized related workspaces.

        Search always starts at ``workspace_id``. Only explicit outbound
        relationships are followed (no implicit global). Cycles are skipped.
        """
        if workspace_id not in self._workspaces:
            raise RelationshipValidationError(f"unknown workspace: {workspace_id!r}")
        if max_depth < 1:
            return []

        results: list[ExpandedTarget] = []
        visited = {workspace_id}
        frontier: list[tuple[str, tuple[str, ...], int]] = [(workspace_id, (), 0)]

        while frontier:
            current, path, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            workspace = self._workspaces.get(current)
            for rel in workspace.relationships:
                self._validate_type(rel.type)
                target = rel.target
                if target in visited:
                    continue
                if principal is not None and not principal.allows_workspace(target):
                    continue
                if target not in self._workspaces:
                    continue
                visited.add(target)
                via = (*path, current)
                results.append(
                    ExpandedTarget(
                        workspace_id=target,
                        via=via,
                        relationship_types=(rel.type,),
                    )
                )
                frontier.append((target, via, depth + 1))
        return results

    def related_workspace_ids(
        self,
        workspace_id: str,
        *,
        principal: Principal | None = None,
        include_self: bool = True,
        max_depth: int = 1,
    ) -> list[str]:
        ids = [workspace_id] if include_self else []
        for target in self.expand_related(
            workspace_id,
            principal=principal,
            max_depth=max_depth,
        ):
            ids.append(target.workspace_id)
        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for item in ids:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    @staticmethod
    def _validate_type(rel_type: str) -> None:
        if rel_type not in ALLOWED_RELATIONSHIP_TYPES:
            raise RelationshipValidationError(
                f"unsupported relationship type {rel_type!r}; "
                f"expected one of {sorted(ALLOWED_RELATIONSHIP_TYPES)}"
            )


def relationships_from_dicts(items: Iterable[dict]) -> tuple[Relationship, ...]:
    rels: list[Relationship] = []
    for item in items:
        rel_type = str(item.get("type") or "")
        if rel_type not in ALLOWED_RELATIONSHIP_TYPES:
            raise RelationshipValidationError(f"unsupported relationship type {rel_type!r}")
        rels.append(
            Relationship(
                target=str(item.get("target") or ""),
                type=rel_type,  # type: ignore[arg-type]
                description=str(item.get("description") or ""),
            )
        )
    return tuple(rels)


# Re-export for type checkers
__all__ = [
    "ALLOWED_RELATIONSHIP_TYPES",
    "ExpandedTarget",
    "Relationship",
    "RelationshipRegistry",
    "RelationshipType",
    "RelationshipValidationError",
    "relationships_from_dicts",
]
