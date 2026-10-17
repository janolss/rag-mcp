"""Source listing via the application service layer."""

from __future__ import annotations

import json
from pathlib import Path

from rag.config import (
    CapabilitiesConfig,
    Config,
    EmbeddingConfig,
    IndexConfig,
    McpConfig,
    QdrantConfig,
)
from rag.services import ServiceApp
from tests.workspace_fixtures import with_workspace_manifest


def test_list_sources_for_workspace_and_overview(tmp_path: Path):
    config = with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="src"),
            index=IndexConfig(
                repo_root=str(tmp_path),
                sources="knowledge",
                knowledge=["docs/**/*.md"],
                code=[],
                apps=[{"prefix": "apps/web/", "name": "web"}],
            ),
            mcp=McpConfig(capabilities=CapabilitiesConfig(knowledge=True, code=False, lis=False)),
        ),
        tmp_path,
    )
    app = ServiceApp(config)
    sources = app.sources.list_sources("default")
    assert any(s.get("id") == "knowledge" or s.get("bucket") == "knowledge" for s in sources)

    overview = app.sources.list_sources(None)
    assert overview
    assert overview[0]["workspace_id"] == "default"
    assert overview[0]["sources"]

    resource = json.loads(app.sources.sources_resource())
    assert resource["ok"] is True
    assert "workspaces" in resource
