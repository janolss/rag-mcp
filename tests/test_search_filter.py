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
