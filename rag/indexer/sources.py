"""Source roots and ignore rules for workspace indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag.config import DEFAULT_IGNORE_DIRS, IndexConfig


@dataclass(frozen=True)
class SourceSpec:
    """A glob relative to repo root plus which index source bucket it belongs to."""

    pattern: str
    bucket: str  # knowledge | code


def selected_sources(index: IndexConfig) -> tuple[SourceSpec, ...]:
    mode = (index.sources or "all").strip().lower()
    knowledge = tuple(SourceSpec(pattern, "knowledge") for pattern in index.knowledge)
    code = tuple(SourceSpec(pattern, "code") for pattern in index.code)

    if mode == "knowledge":
        return knowledge
    if mode == "code":
        return code
    if mode == "all":
        return knowledge + code
    raise ValueError(f"Unsupported index.sources value: {index.sources!r} (use knowledge|code|all)")


def should_ignore(path: Path, repo_root: Path, ignore_dirs: list[str] | None = None) -> bool:
    names = set(ignore_dirs if ignore_dirs is not None else DEFAULT_IGNORE_DIRS)
    try:
        rel_parts = path.resolve().relative_to(repo_root.resolve()).parts
    except ValueError:
        return True
    return any(part in names for part in rel_parts)
