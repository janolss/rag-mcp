"""Walk configured source globs and yield readable text files."""

from __future__ import annotations

import fnmatch
import glob as globmod
import logging
from pathlib import Path

from rag.domain.models import Source
from rag.indexer.sources import SourceSpec, should_ignore
from rag.security.paths import PathSecurityPolicy, SecurePathError, assert_within_roots

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


def path_identity_for_indexing(
    path: Path,
    *,
    source_root: Path | str | None = None,
    workspace_root: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> str:
    """
    Build the path identity used for ``file`` / app / documentation matching.

    Prefer workspace root, then source root, then repo root so ``index.apps``
    prefixes like ``apps/web/`` match files whose Source.root lives outside
    ``config.index.repo_root``. Falls back to an absolute posix path.
    """
    resolved = path.resolve()
    for raw in (workspace_root, source_root, repo_root):
        if raw is None or str(raw).strip() == "":
            continue
        root = Path(raw).resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def matches_exclude(path: Path, root: Path, exclude: tuple[str, ...] | list[str]) -> bool:
    """Return True when ``path`` matches a source exclude rule (dir name or glob)."""
    if not exclude:
        return False
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = resolved.as_posix()
    parts = Path(rel).parts
    for rule in exclude:
        text = (rule or "").strip()
        if not text:
            continue
        if any(ch in text for ch in "*?[") or "/" in text or "\\" in text:
            if fnmatch.fnmatch(rel, text.replace("\\", "/")):
                return True
            continue
        if text in parts or text == Path(rel).name:
            return True
    return False


def walk_source(
    source: Source,
    *,
    ignore_dirs: list[str] | None = None,
    policy: PathSecurityPolicy | None = None,
    identity_root: Path | None = None,
) -> list[tuple[Path, str, str]]:
    """
    Walk one registered ``Source`` root with its include/exclude patterns.

    Returns ``(absolute_path, source_id, bucket)`` sorted by path. Paths must
    stay inside ``source.root`` (path security). ``identity_root`` is only used
    by callers for stable path keys and is not required here.
    """
    del identity_root  # reserved for callers that need repo-relative identities
    root = Path(source.root).resolve()
    if not root.exists():
        logger.warning("Skipping missing source root %s (%s)", source.id, root)
        return []

    active_policy = policy or PathSecurityPolicy()
    includes = list(source.include) if source.include else ["**/*"]
    bucket = source.bucket or source.id
    found: dict[Path, tuple[str, str]] = {}

    for pattern in includes:
        for path in expand_glob(root, pattern):
            if should_ignore(path, root, ignore_dirs):
                continue
            if matches_exclude(path, root, source.exclude):
                continue
            try:
                secure = assert_within_roots(path, [root], policy=active_policy)
            except SecurePathError as exc:
                logger.warning("Skipping unsafe path during source walk: %s", exc)
                continue
            found[secure] = (source.id, bucket)

    files = sorted(
        ((path, source_id, source_bucket) for path, (source_id, source_bucket) in found.items()),
        key=lambda item: item[0].as_posix(),
    )
    logger.info("Discovered %d files for source %s under %s", len(files), source.id, root)
    return files


def walk_files(
    repo_root: Path,
    specs: tuple[SourceSpec, ...],
    ignore_dirs: list[str] | None = None,
    *,
    policy: PathSecurityPolicy | None = None,
    extra_roots: list[Path] | tuple[Path, ...] | None = None,
) -> list[tuple[Path, str]]:
    """
    Return unique existing files matching the source specs, sorted.

    Each entry is ``(absolute_path, bucket)``. Later specs overwrite the bucket
    when the same file matches multiple globs (lis wins over knowledge/code if
    listed last).

    Absolute patterns must resolve under ``repo_root`` or an explicitly provided
    ``extra_roots`` entry (registered external mirrors).
    """
    found: dict[Path, str] = {}
    root = repo_root.resolve()
    active_policy = policy or PathSecurityPolicy()
    roots: list[Path] = [root, *(Path(r).resolve() for r in (extra_roots or ()))]

    for spec in specs:
        for path in expand_glob(root, spec.pattern):
            if should_ignore(path, root, ignore_dirs):
                continue
            try:
                secure = assert_within_roots(path, roots, policy=active_policy)
            except SecurePathError as exc:
                logger.warning("Skipping unsafe path during walk: %s", exc)
                continue
            found[secure] = spec.bucket

    files = sorted(found.items(), key=lambda item: item[0].as_posix())
    logger.info("Discovered %d files under %s", len(files), root)
    return files


def read_text_file(
    path: Path,
    *,
    policy: PathSecurityPolicy | None = None,
    roots: list[Path] | tuple[Path, ...] | None = None,
) -> str:
    """Read a text file, optionally enforcing path security first."""
    if policy is not None and roots is not None:
        canonical = assert_within_roots(path, roots, policy=policy)
        return canonical.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")
