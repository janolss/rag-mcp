"""Domain model smoke tests."""

from __future__ import annotations

from rag.domain.models import Relationship, Source, Workspace


def test_workspace_source_lookup_and_immutability():
    source = Source(
        id="backend",
        type="source_code",
        root="/projects/app",
        include=("src/**/*.py",),
        bucket="code",
    )
    workspace = Workspace(
        id="app",
        name="App",
        sources=(source,),
        relationships=(Relationship(target="shared-auth", type="depends_on"),),
        tags=("backend",),
    )
    assert workspace.source_by_id("backend") is source
    assert workspace.source_by_id("missing") is None
    assert workspace.relationships[0].target == "shared-auth"


def test_workspace_defaults():
    workspace = Workspace(id="default", name="Default")
    assert workspace.sources == ()
    assert workspace.legacy is False
    assert workspace.metadata == {}
