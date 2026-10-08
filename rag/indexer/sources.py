"""Source roots and ignore rules for workspace indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag.config import (
    DEFAULT_IGNORE_DIRS,
    CapabilitiesConfig,
    Config,
    IndexConfig,
    parse_sources_mode,
)


@dataclass(frozen=True)
class SourceSpec:
    """A glob relative to repo root (or absolute) plus which index bucket it belongs to."""

    pattern: str
    bucket: str  # knowledge | code | lis


def selected_sources(
    index: IndexConfig,
    *,
    capabilities: CapabilitiesConfig | None = None,
    enabled_buckets: set[str] | None = None,
) -> tuple[SourceSpec, ...]:
    """
    Build source specs for the requested buckets.

    Prefer passing ``enabled_buckets`` from ``Config.enabled_buckets()`` so
    ``index.sources`` and ``mcp.capabilities`` stay aligned.
    """
    if enabled_buckets is not None:
        wanted = set(enabled_buckets)
    else:
        wanted = parse_sources_mode(index.sources)
        if capabilities is not None:
            if not capabilities.knowledge:
                wanted.discard("knowledge")
            if not capabilities.code:
                wanted.discard("code")
            if not capabilities.lis:
                wanted.discard("lis")

    specs: list[SourceSpec] = []
    if "knowledge" in wanted:
        specs.extend(SourceSpec(pattern, "knowledge") for pattern in index.knowledge)
    if "code" in wanted:
        specs.extend(SourceSpec(pattern, "code") for pattern in index.code)
    if "lis" in wanted:
        specs.extend(SourceSpec(pattern, "lis") for pattern in index.lis)
    return tuple(specs)


def selected_sources_for_config(config: Config) -> tuple[SourceSpec, ...]:
    return selected_sources(config.index, enabled_buckets=config.enabled_buckets())


def should_ignore(path: Path, repo_root: Path, ignore_dirs: list[str] | None = None) -> bool:
    names = set(ignore_dirs if ignore_dirs is not None else DEFAULT_IGNORE_DIRS)
    try:
        rel_parts = path.resolve().relative_to(repo_root.resolve()).parts
    except ValueError:
        # Outside repo_root (e.g. absolute LIS mirror): ignore only if any path part matches
        rel_parts = path.resolve().parts
    return any(part in names for part in rel_parts)
