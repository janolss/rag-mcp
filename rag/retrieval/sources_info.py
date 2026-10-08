"""Config-driven source listing for MCP tools/resources."""

from __future__ import annotations

import json

from rag.config import Config


def list_sources_payload(config: Config) -> dict:
    caps = config.mcp.capabilities
    return {
        "repo_root": str(config.repo_root_path),
        "sources": config.index.sources,
        "enabled_buckets": sorted(config.enabled_buckets()),
        "capabilities": {
            "knowledge": caps.knowledge,
            "code": caps.code,
            "lis": caps.lis,
        },
        "collection": config.qdrant.collection,
        "qdrant_mode": config.qdrant.mode,
        "knowledge_globs": list(config.index.knowledge),
        "code_globs": list(config.index.code),
        "lis_globs": list(config.index.lis),
        "documentation_prefixes": list(config.index.documentation_prefixes),
        "ignore_dirs": list(config.index.ignore_dirs),
        "apps": [{"prefix": a.prefix, "name": a.name} for a in config.index.apps],
        "requirement_id_patterns": list(config.index.requirement_id_patterns),
    }


def list_sources(config: Config) -> str:
    return json.dumps(list_sources_payload(config), indent=2) + "\n"
