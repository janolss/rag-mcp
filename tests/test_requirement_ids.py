from rag.indexer.requirement_ids import (
    extract_requirement_ids,
    matches_requirement_id_pattern,
    normalize_requirement_query,
)


def test_extract_requirement_ids_unique_sorted():
    text = "See REQ-2 and req-10; also KR-1 and US-99. REQ-2 again."
    assert extract_requirement_ids(text) == ["KR-1", "REQ-10", "REQ-2", "US-99"]


def test_matches_and_normalize_id():
    assert matches_requirement_id_pattern("req-12")
    assert normalize_requirement_query("req-12") == "REQ-12"
    assert normalize_requirement_query("tenant isolation") == "tenant isolation"
