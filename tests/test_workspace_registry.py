"""Workspace registry behavior."""

from __future__ import annotations

import pytest
from rag.domain.models import Workspace
from rag.workspaces.registry import (
    DuplicateWorkspaceError,
    WorkspaceNotFoundError,
    WorkspaceRegistry,
)


def test_register_list_get_and_query():
    registry = WorkspaceRegistry()
    registry.register(Workspace(id="alpha", name="Alpha", tags=("saas",), description="A"))
    registry.register(Workspace(id="beta", name="Beta", tags=("lib", "saas"), description="B"))

    assert len(registry) == 2
    assert "alpha" in registry
    assert registry.get("alpha").name == "Alpha"
    assert [ws.id for ws in registry.list()] == ["alpha", "beta"]
    assert [ws.id for ws in registry.list(query="bet")] == ["beta"]
    assert [ws.id for ws in registry.list(tags=["saas"])] == ["alpha", "beta"]
    assert [ws.id for ws in registry.list(tags=["lib"])] == ["beta"]


def test_duplicate_and_unknown_workspace():
    registry = WorkspaceRegistry([Workspace(id="only", name="Only")])
    with pytest.raises(DuplicateWorkspaceError):
        registry.register(Workspace(id="only", name="Again"))
    with pytest.raises(WorkspaceNotFoundError):
        registry.get("missing")


def test_replace_all_is_atomic_on_duplicate():
    registry = WorkspaceRegistry([Workspace(id="keep", name="Keep")])
    with pytest.raises(DuplicateWorkspaceError):
        registry.replace_all(
            [
                Workspace(id="a", name="A"),
                Workspace(id="a", name="A2"),
            ]
        )
    assert registry.ids() == ["keep"]

    registry.replace_all(
        [
            Workspace(id="one", name="One"),
            Workspace(id="two", name="Two"),
        ]
    )
    assert registry.ids() == ["one", "two"]
