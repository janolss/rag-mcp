import pytest
from qdrant_client import models
from rag.store import (
    ScopeDisabledError,
    WorkspaceFilterError,
    build_type_app_filter,
)


def test_filter_none_when_no_constraints_legacy():
    assert build_type_app_filter(allow_legacy=True) is None


def test_filter_requires_workspace_without_legacy():
    with pytest.raises(WorkspaceFilterError, match="workspace_id is required"):
        build_type_app_filter()


def test_filter_type_only():
    filt = build_type_app_filter(workspace_id="default", type_filter=["documentation"])
    assert isinstance(filt, models.Filter)
    keys = {c.key for c in filt.must}
    assert keys == {"workspace_id", "type"}


def test_filter_type_and_app():
    filt = build_type_app_filter(
        workspace_id="default",
        type_filter=["code", "test"],
        app_filter="web",
    )
    keys = {c.key for c in filt.must}
    assert keys == {"workspace_id", "type", "app"}


def test_filter_requirement_id():
    filt = build_type_app_filter(workspace_id="default", requirement_id="REQ-42")
    keys = {c.key for c in filt.must}
    assert keys == {"workspace_id", "requirement_ids"}
    req = next(c for c in filt.must if c.key == "requirement_ids")
    assert req.match.value == "REQ-42"


def test_filter_lis_fields():
    filt = build_type_app_filter(
        workspace_id="default",
        type_filter=["lis"],
        doc_type="anvisning",
        process_area="utveckla",
        domain="infosec",
        status="approved",
    )
    assert isinstance(filt, models.Filter)
    keys = {c.key for c in filt.must}
    assert keys == {
        "workspace_id",
        "type",
        "doc_type",
        "process_area",
        "domain",
        "status",
    }


def test_filter_source_document_language():
    filt = build_type_app_filter(
        workspace_id="ws",
        source_id="code",
        document_id="apps/web/a.ts",
        language="typescript",
    )
    keys = {c.key for c in filt.must}
    assert keys == {"workspace_id", "source_id", "document_id", "language"}


def test_scope_source_requires_source_id():
    with pytest.raises(ValueError, match="source_id"):
        build_type_app_filter(workspace_id="ws", scope="source")


def test_scope_related_requires_expansion_global_disabled():
    with pytest.raises(ValueError, match="related_workspace_ids"):
        build_type_app_filter(workspace_id="ws", scope="related")
    with pytest.raises(ScopeDisabledError, match="global"):
        build_type_app_filter(workspace_id="ws", scope="global")
