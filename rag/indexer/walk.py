"""Walk configured source globs and yield readable text files."""

from __future__ import annotations

import logging
from pathlib import Path

from rag.indexer.sources import SourceSpec, should_ignore

logger = logging.getLogger(__name__)


def walk_files(
    repo_root: Path,
    specs: tuple[SourceSpec, ...],
    ignore_dirs: list[str] | None = None,
) -> list[Path]:
    """Return unique existing files matching the source specs, sorted."""
    found: set[Path] = set()
    root = repo_root.resolve()

    for spec in specs:
        matches = sorted(root.glob(spec.pattern))
        for path in matches:
            if not path.is_file():
                continue
            if should_ignore(path, root, ignore_dirs):
                continue
            found.add(path.resolve())

    files = sorted(found)
    logger.info("Discovered %d files under %s", len(files), root)
    return files


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
