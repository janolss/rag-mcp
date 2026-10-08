"""Walk configured source globs and yield readable text files."""

from __future__ import annotations

import glob as globmod
import logging
from pathlib import Path

from rag.indexer.sources import SourceSpec, should_ignore

logger = logging.getLogger(__name__)


def expand_glob(repo_root: Path, pattern: str) -> list[Path]:
    """Expand a relative (to repo_root) or absolute filesystem glob to files."""
    pattern = (pattern or "").strip()
    if not pattern:
        return []

    root = repo_root.resolve()
    # Absolute patterns (LIS mirrors often live outside the workspace)
    if Path(pattern).is_absolute():
        matches = [Path(p) for p in globmod.glob(pattern, recursive=True)]
    else:
        matches = list(root.glob(pattern))

    files: list[Path] = []
    for path in matches:
        if path.is_file():
            files.append(path.resolve())
    return files


def file_identity(path: Path, repo_root: Path) -> str:
    """Stable path key: repo-relative when possible, else absolute posix path."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def walk_files(
    repo_root: Path,
    specs: tuple[SourceSpec, ...],
    ignore_dirs: list[str] | None = None,
) -> list[tuple[Path, str]]:
    """
    Return unique existing files matching the source specs, sorted.

    Each entry is ``(absolute_path, bucket)``. Later specs overwrite the bucket
    when the same file matches multiple globs (lis wins over knowledge/code if
    listed last).
    """
    found: dict[Path, str] = {}
    root = repo_root.resolve()

    for spec in specs:
        for path in expand_glob(root, spec.pattern):
            if should_ignore(path, root, ignore_dirs):
                continue
            found[path] = spec.bucket

    files = sorted(found.items(), key=lambda item: item[0].as_posix())
    logger.info("Discovered %d files under %s", len(files), root)
    return files


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
