"""Unit tests for list_sources formatting."""

from rag.config import AppRule, Config, IndexConfig, QdrantConfig, DEFAULT_MCP_INSTRUCTIONS
from rag.retrieval.sources_info import list_sources, list_sources_payload


def test_list_sources_includes_apps_and_globs():
    config = Config(
        qdrant=QdrantConfig(mode="memory", collection="src_test"),
        index=IndexConfig(
            repo_root="/tmp/workspace",
            knowledge=["docs/**/*.md"],
            code=["apps/**/*.ts"],
            apps=[AppRule(prefix="apps/web/", name="web")],
            requirement_id_patterns=[r"REQ-\d+"],
        ),
    )
    payload = list_sources_payload(config)
    assert payload["collection"] == "src_test"
    assert payload["qdrant_mode"] == "memory"
    assert payload["knowledge_globs"] == ["docs/**/*.md"]
    assert payload["apps"] == [{"prefix": "apps/web/", "name": "web"}]
    assert payload["requirement_id_patterns"] == [r"REQ-\d+"]

    text = list_sources(config)
    assert '"name": "web"' in text
    assert "docs/**/*.md" in text


def test_default_instructions_contain_workflow():
    assert "index_status" in DEFAULT_MCP_INSTRUCTIONS
    assert "get_context_pack" in DEFAULT_MCP_INSTRUCTIONS
    assert "trace_requirement" in DEFAULT_MCP_INSTRUCTIONS
    assert "find_gaps" in DEFAULT_MCP_INSTRUCTIONS
