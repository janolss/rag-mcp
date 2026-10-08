from qdrant_client import models

from rag.store import build_type_app_filter


def test_filter_none_when_no_constraints():
    assert build_type_app_filter() is None


def test_filter_type_only():
    filt = build_type_app_filter(type_filter=["documentation"])
    assert isinstance(filt, models.Filter)
    assert len(filt.must) == 1
    condition = filt.must[0]
    assert condition.key == "type"
    assert condition.match.any == ["documentation"]


def test_filter_type_and_app():
    filt = build_type_app_filter(type_filter=["code", "test"], app_filter="web")
    assert len(filt.must) == 2
    keys = {c.key for c in filt.must}
    assert keys == {"type", "app"}


def test_filter_requirement_id():
    filt = build_type_app_filter(requirement_id="REQ-42")
    assert len(filt.must) == 1
    assert filt.must[0].key == "requirement_ids"
    assert filt.must[0].match.value == "REQ-42"


def test_filter_lis_fields():
    filt = build_type_app_filter(
        type_filter=["lis"],
        doc_type="anvisning",
        process_area="utveckla",
        domain="infosec",
        status="approved",
    )
    assert isinstance(filt, models.Filter)
    keys = {c.key for c in filt.must}
    assert keys == {"type", "doc_type", "process_area", "domain", "status"}
