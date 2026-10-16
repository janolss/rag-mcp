"""Workspace relationship validation and related-scope tests."""

from __future__ import annotations

import pytest
from rag.domain.models import Relationship, Workspace
from rag.relationships.registry import (
    RelationshipRegistry,
    RelationshipValidationError,
)
from rag.security.access import Principal
from rag.store import ScopeDisabledError, build_type_app_filter
from rag.workspaces.registry import WorkspaceRegistry


def _registry() -> WorkspaceRegistry:
    return WorkspaceRegistry(
        [
            Workspace(
                id="app",
                name="App",
                relationships=(
                    Relationship(target="shared", type="depends_on"),
                    Relationship(target="docs", type="documents"),
                ),
            ),
            Workspace(id="shared", name="Shared"),
            Workspace(id="docs", name="Docs"),
            Workspace(id="secret", name="Secret"),
        ]
    )


def test_validate_unknown_target_and_types():
    registry = WorkspaceRegistry(
        [
            Workspace(
                id="a",
                name="A",
                relationships=(Relationship(target="missing", type="depends_on"),),
            )
        ]
    )
    rel = RelationshipRegistry.from_workspace_registry(registry)
    with pytest.raises(RelationshipValidationError, match="unknown relationship target"):
        rel.validate_all()

    bad = Workspace(
        id="a",
        name="A",
        relationships=(Relationship(target="b", type="likes"),),  # type: ignore[arg-type]
    )
    registry2 = WorkspaceRegistry([bad, Workspace(id="b", name="B")])
    with pytest.raises(RelationshipValidationError, match="unsupported relationship type"):
        RelationshipRegistry.from_workspace_registry(registry2).validate_workspace(bad)


def test_expand_related_with_acl_and_cycles():
    registry = _registry()
    # Add a cycle shared -> app
    shared = registry.get("shared")
    registry.replace_all(
        [
            registry.get("app"),
            Workspace(
                id="shared",
                name="Shared",
                relationships=(Relationship(target="app", type="references"),),
            ),
            registry.get("docs"),
            registry.get("secret"),
        ]
    )
    del shared
    rel = RelationshipRegistry.from_workspace_registry(registry)
    principal = Principal(
        subject="dev",
        workspace_allowlist=frozenset({"app", "shared", "docs"}),
    )
    expanded = rel.related_workspace_ids("app", principal=principal, max_depth=2)
    assert expanded[0] == "app"
    assert "shared" in expanded
    assert "docs" in expanded
    assert "secret" not in expanded


def test_related_scope_filter_and_global_disabled():
    filt = build_type_app_filter(
        workspace_id="app",
        scope="related",
        related_workspace_ids=["app", "shared"],
    )
    assert filt is not None
    keys = {c.key for c in filt.must}
    assert "workspace_id" in keys

    with pytest.raises(ScopeDisabledError, match="global"):
        build_type_app_filter(workspace_id="app", scope="global")

    with pytest.raises(ValueError, match="related_workspace_ids"):
        build_type_app_filter(workspace_id="app", scope="related")
