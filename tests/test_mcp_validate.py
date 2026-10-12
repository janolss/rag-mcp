from rag.mcp_validate import (
    require_nonempty,
    validate_lis_filters,
    validate_top_k,
)


def test_require_nonempty():
    assert require_nonempty("query", "") is not None
    assert require_nonempty("query", "  ") is not None
    assert require_nonempty("query", None) is not None
    assert require_nonempty("query", "hello") is None


def test_validate_top_k():
    assert validate_top_k(None) is None
    assert validate_top_k(1) is None
    assert validate_top_k(50) is None
    assert validate_top_k(0) is not None
    assert validate_top_k(51) is not None


def test_validate_lis_filters():
    assert validate_lis_filters(doc_type="anvisning", process_area="utveckla", status="approved") is None
    assert validate_lis_filters(doc_type="nope") is not None
    assert validate_lis_filters(process_area="unknown") is not None
    assert validate_lis_filters(status="pending") is not None
