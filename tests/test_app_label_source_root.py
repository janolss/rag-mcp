"""App labels must match against workspace/source-relative paths."""

from __future__ import annotations

from pathlib import Path

from rag.config import AppRule, load_config
from rag.indexer.run import build_chunks
from rag.indexer.walk import path_identity_for_indexing


def test_path_identity_prefers_workspace_then_source_root(tmp_path: Path):
    workspace = tmp_path / "lk_apps"
    file_path = workspace / "apps" / "web" / "middleware" / "tenantContext.ts"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("export {}\n", encoding="utf-8")
    rag_repo = tmp_path / "rag-mcp"
    rag_repo.mkdir()

    identity = path_identity_for_indexing(
        file_path,
        workspace_root=workspace,
        source_root=workspace,
        repo_root=rag_repo,
    )
    assert identity == "apps/web/middleware/tenantContext.ts"


def test_build_chunks_stamps_app_from_source_relative_path(tmp_path: Path):
    """Manifest source outside config.repo_root still gets index.apps labels."""
    project = tmp_path / "github_repo" / "lk_apps"
    web = project / "apps" / "web" / "middleware"
    web.mkdir(parents=True)
    target = web / "tenantContext.ts"
    target.write_text(
        "export function tenantContext() { return 'tenant'; }\n",
        encoding="utf-8",
    )

    rag_home = tmp_path / "mcp-servers"
    rag_home.mkdir()

    manifest = tmp_path / "lk_apps.yaml"
    manifest.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "id: lk_apps",
                "name: Example Apps",
                "roots:",
                "  - id: applications",
                f"    path: {project}",
                "    type: source_code",
                "    include:",
                '      - "apps/**/*.ts"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "workspace_manifests:\n"
        f"  - {manifest}\n"
        "index:\n"
        f"  repo_root: {rag_home}\n"
        f"  status_file: {tmp_path / 'status.json'}\n"
        "  sources: code\n"
        "  knowledge: []\n"
        "  code: []\n"
        "  apps:\n"
        "    - prefix: apps/web/\n"
        "      name: web\n"
        "qdrant:\n  mode: memory\n  collection: apps\n"
        "embedding:\n  model: fake\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.app_names == {"web"}
    assert any(isinstance(rule, AppRule) for rule in config.index.apps)

    chunks = build_chunks(config, workspace_id="lk_apps")
    assert chunks
    assert all(c["file"] == "apps/web/middleware/tenantContext.ts" for c in chunks)
    assert all(c["app"] == "web" for c in chunks)
    assert all(c["workspace_id"] == "lk_apps" for c in chunks)
    assert all(c["source_id"] == "applications" for c in chunks)
