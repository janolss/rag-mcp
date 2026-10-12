import json

from rag.mcp_results import as_tool_result, resource_error, resource_ok, tool_error


def test_as_tool_result_marks_errors():
    ok = as_tool_result("No relevant results found.")
    assert ok.is_error is False
    assert "No relevant results found" in ok.content[0].text

    err = as_tool_result("Error: Qdrant locked")
    assert err.is_error is True
    assert "Qdrant locked" in err.content[0].text


def test_tool_error_prefix():
    result = tool_error("boom")
    assert result.is_error
    assert result.content[0].text.startswith("Error:")


def test_resource_envelope_is_json():
    ok = json.loads(resource_ok({"points_count": 3}))
    assert ok["ok"] is True
    assert ok["points_count"] == 3

    err = json.loads(resource_error("locked"))
    assert err["ok"] is False
    assert err["error"] == "locked"
