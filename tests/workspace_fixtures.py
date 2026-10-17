"""Shared helpers to attach a workspace.yaml to test Config objects."""

from __future__ import annotations

from pathlib import Path

import yaml
from rag.config import Config


def write_workspace_manifest(
    path: Path,
    *,
    workspace_id: str = "default",
    name: str | None = None,
    root: Path | str,
    sources: list[dict] | None = None,
) -> Path:
    """Write a minimal schema_version=1 workspace manifest."""
    root_path = Path(root)
    if sources is None:
        sources = [
            {
                "id": "knowledge",
                "path": str(root_path),
                "type": "architecture_docs",
                "include": ["**/*.md"],
            }
        ]
    payload = {
        "schema_version": 1,
        "id": workspace_id,
        "name": name or workspace_id,
        "roots": sources,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def sources_from_index(config: Config, root: Path) -> list[dict]:
    """Build manifest roots from index.* globs (test convenience)."""
    sources: list[dict] = []
    enabled = config.enabled_buckets()
    if "knowledge" in enabled and config.index.knowledge:
        sources.append(
            {
                "id": "knowledge",
                "path": str(root),
                "type": "architecture_docs",
                "include": list(config.index.knowledge),
            }
        )
    if "code" in enabled and config.index.code:
        sources.append(
            {
                "id": "code",
                "path": str(root),
                "type": "source_code",
                "include": list(config.index.code),
            }
        )
    if "lis" in enabled and config.index.lis:
        lis_root = root
        includes: list[str] = []
        for pattern in config.index.lis:
            p = Path(pattern)
            if p.is_absolute():
                parts = p.parts
                if "**" in parts:
                    lis_root = Path(*parts[: parts.index("**")])
                    includes.append("**/{}".format("/".join(parts[parts.index("**") + 1 :])))
                else:
                    lis_root = p.parent if p.suffix else p
                    includes.append(p.name if p.suffix else "**/*")
            else:
                includes.append(pattern)
        sources.append(
            {
                "id": "lis",
                "path": str(lis_root),
                "type": "policies",
                "include": includes or list(config.index.lis),
            }
        )
    if not sources:
        sources.append(
            {
                "id": "knowledge",
                "path": str(root),
                "type": "architecture_docs",
                "include": ["**/*.md"],
            }
        )
    return sources


def with_workspace_manifest(
    config: Config,
    tmp_path: Path,
    *,
    workspace_id: str = "default",
    manifest_name: str = "workspace.yaml",
) -> Config:
    """Return a copy of config with a generated workspace_manifests entry."""
    root = config.repo_root_path
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / manifest_name
    write_workspace_manifest(
        manifest_path,
        workspace_id=workspace_id,
        name=config.mcp.name or workspace_id,
        root=root,
        sources=sources_from_index(config, root),
    )
    return config.model_copy(update={"workspace_manifests": [str(manifest_path)]})
