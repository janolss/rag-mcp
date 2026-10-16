"""Adapt the existing single-repo config into a synthetic default workspace."""

from __future__ import annotations

from pathlib import Path

from rag.config import Config
from rag.domain.models import Source, Workspace


def _legacy_sources(config: Config) -> tuple[Source, ...]:
    """Translate knowledge/code/lis globs into explicit Source objects."""
    repo_root = str(config.repo_root_path)
    enabled = config.enabled_buckets()
    sources: list[Source] = []

    if "knowledge" in enabled and config.index.knowledge:
        sources.append(
            Source(
                id="knowledge",
                type="architecture_docs",
                root=repo_root,
                include=tuple(config.index.knowledge),
                exclude=tuple(config.index.ignore_dirs),
                adapter="filesystem",
                status="not_indexed",
                description="Legacy knowledge globs",
                bucket="knowledge",
            )
        )
    if "code" in enabled and config.index.code:
        sources.append(
            Source(
                id="code",
                type="source_code",
                root=repo_root,
                include=tuple(config.index.code),
                exclude=tuple(config.index.ignore_dirs),
                adapter="filesystem",
                status="not_indexed",
                description="Legacy code globs",
                bucket="code",
            )
        )
    if "lis" in enabled and config.index.lis:
        # Absolute LIS mirrors keep their first absolute pattern directory when possible.
        lis_root = repo_root
        for pattern in config.index.lis:
            path = Path(pattern)
            if path.is_absolute():
                lis_root = str(path.parent if path.suffix else path)
                break
        sources.append(
            Source(
                id="lis",
                type="policies",
                root=lis_root,
                include=tuple(config.index.lis),
                exclude=tuple(config.index.ignore_dirs),
                adapter="filesystem",
                status="not_indexed",
                description="Legacy LIS globs",
                bucket="lis",
            )
        )
    return tuple(sources)


def workspace_from_config(config: Config, *, workspace_id: str = "default") -> Workspace:
    """Build the synthetic default workspace from current Config."""
    name = config.mcp.name or "default"
    return Workspace(
        id=workspace_id,
        name=name,
        description="Synthetic workspace derived from legacy config.yaml",
        technologies=(),
        tags=(),
        instructions=tuple(
            line.strip() for line in (config.mcp.instructions or "").splitlines() if line.strip()
        )[:8],
        sources=_legacy_sources(config),
        relationships=(),
        root_path=str(config.repo_root_path),
        legacy=True,
        metadata={
            "collection": config.qdrant.collection,
            "qdrant_mode": config.qdrant.mode,
            "sources_mode": config.index.sources,
        },
    )
