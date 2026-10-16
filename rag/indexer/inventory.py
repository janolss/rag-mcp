"""Hash-based inventory: classify documents as new/changed/unchanged/deleted."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rag.config import Config
from rag.indexer.document_registry import DocumentRecord, DocumentRegistry
from rag.indexer.identity import content_hash, normalize_document_id
from rag.indexer.sources import selected_sources_for_config
from rag.indexer.walk import file_identity, read_text_file, walk_files
from rag.security.paths import PathSecurityPolicy, SecurePathError, assert_within_roots

InventoryKind = Literal["new", "changed", "unchanged", "deleted"]


@dataclass(frozen=True)
class InventoryItem:
    workspace_id: str
    source_id: str
    document_id: str
    path: str
    content_hash: str
    kind: InventoryKind
    absolute_path: Path | None = None
    previous: DocumentRecord | None = None


@dataclass(frozen=True)
class ObservedDocument:
    """A document currently present on disk (or an explicit path list)."""

    workspace_id: str
    source_id: str
    document_id: str
    path: str
    content_hash: str
    absolute_path: Path | None = None


@dataclass
class InventoryDiff:
    new: list[ObservedDocument] = field(default_factory=list)
    changed: list[tuple[ObservedDocument, DocumentRecord]] = field(default_factory=list)
    unchanged: list[tuple[ObservedDocument, DocumentRecord]] = field(default_factory=list)
    deleted: list[DocumentRecord] = field(default_factory=list)

    @property
    def actionable(self) -> list[ObservedDocument]:
        return [*self.new, *[obs for obs, _prev in self.changed]]


def inventory_files(
    *,
    registry: DocumentRegistry,
    workspace_id: str,
    source_id: str,
    files: Sequence[tuple[Path, str]],
    root: Path,
) -> list[InventoryItem]:
    """
    Classify explicit ``(absolute_path, bucket)`` pairs against the registry.

    Also emits ``deleted`` items for registry rows under ``source_id`` that are
    missing from ``files``.
    """
    root = root.resolve()
    observed: dict[str, ObservedDocument] = {}
    for path, bucket in files:
        resolved = Path(path).resolve()
        identity = file_identity(resolved, root)
        document_id = normalize_document_id(identity)
        text = read_text_file(resolved)
        observed[document_id] = ObservedDocument(
            workspace_id=workspace_id,
            source_id=bucket or source_id,
            document_id=document_id,
            path=identity,
            content_hash=content_hash(text),
            absolute_path=resolved,
        )

    known = {
        record.document_id: record
        for record in registry.list_workspace(workspace_id, include_deleted=True)
        if record.source_id == source_id or source_id == "*"
    }

    items: list[InventoryItem] = []
    for document_id, obs in sorted(observed.items()):
        previous = known.get(document_id)
        if previous is None or previous.status == "deleted":
            kind: InventoryKind = "new"
        elif previous.content_hash == obs.content_hash and previous.status == "active":
            kind = "unchanged"
        else:
            kind = "changed"
        items.append(
            InventoryItem(
                workspace_id=obs.workspace_id,
                source_id=obs.source_id,
                document_id=obs.document_id,
                path=obs.path,
                content_hash=obs.content_hash,
                kind=kind,
                absolute_path=obs.absolute_path,
                previous=previous if kind != "new" else None,
            )
        )

    for document_id, record in sorted(known.items()):
        if record.status == "deleted":
            continue
        if document_id in observed:
            continue
        items.append(
            InventoryItem(
                workspace_id=record.workspace_id,
                source_id=record.source_id,
                document_id=record.document_id,
                path=record.path or record.document_id,
                content_hash=record.content_hash,
                kind="deleted",
                previous=record,
            )
        )
    return items


def classify_inventory(
    registry: DocumentRegistry,
    observed: Sequence[ObservedDocument],
    *,
    workspace_id: str,
    scoped_document_ids: set[str] | None = None,
) -> InventoryDiff:
    """
    Compare observed documents against the registry.

    When ``scoped_document_ids`` is set (partial ``index --files``), only those
    document IDs participate in deletion detection.
    """
    diff = InventoryDiff()
    observed_by_id: dict[str, ObservedDocument] = {}
    for item in observed:
        if item.workspace_id != workspace_id:
            continue
        observed_by_id[item.document_id] = item

    known = {
        record.document_id: record
        for record in registry.list_workspace(workspace_id, include_deleted=True)
    }

    for document_id, item in sorted(observed_by_id.items()):
        previous = known.get(document_id)
        if previous is None or previous.status == "deleted":
            diff.new.append(item)
            continue
        if previous.content_hash == item.content_hash and previous.status == "active":
            diff.unchanged.append((item, previous))
        else:
            diff.changed.append((item, previous))

    for document_id, record in sorted(known.items()):
        if record.status == "deleted":
            continue
        if document_id in observed_by_id:
            continue
        if scoped_document_ids is not None and document_id not in scoped_document_ids:
            continue
        diff.deleted.append(record)

    return diff


def observe_paths(
    config: Config,
    rel_paths: Sequence[str],
    *,
    workspace_id: str = "default",
) -> list[ObservedDocument]:
    """Build observed documents for explicit paths (missing paths are omitted)."""
    from rag.indexer.run import _infer_bucket, _registered_extra_roots

    repo_root = config.repo_root_path
    policy = PathSecurityPolicy()
    roots = [repo_root.resolve(), *[r.resolve() for r in _registered_extra_roots(config)]]
    observed: list[ObservedDocument] = []
    seen: set[str] = set()

    for raw in rel_paths:
        raw_norm = (raw or "").replace("\\", "/").strip()
        if not raw_norm:
            continue
        path = Path(raw_norm)
        try:
            if path.is_absolute():
                path = assert_within_roots(path, roots, policy=policy)
                identity = file_identity(path, repo_root)
            else:
                rel = raw_norm.lstrip("./")
                path = assert_within_roots(repo_root / rel, roots, policy=policy)
                identity = rel
        except SecurePathError:
            continue

        document_id = normalize_document_id(identity)
        if document_id in seen:
            continue
        seen.add(document_id)
        if not path.is_file():
            continue

        text = read_text_file(path)
        bucket = _infer_bucket(config, identity, path) or "default"
        observed.append(
            ObservedDocument(
                workspace_id=workspace_id,
                source_id=bucket,
                document_id=document_id,
                path=identity,
                content_hash=content_hash(text),
                absolute_path=path,
            )
        )
    return observed


def observe_workspace(
    config: Config,
    *,
    workspace_id: str = "default",
) -> list[ObservedDocument]:
    """Walk configured sources and hash every readable file."""
    from rag.indexer.run import _registered_extra_roots

    repo_root = config.repo_root_path
    specs = selected_sources_for_config(config)
    files = walk_files(
        repo_root,
        specs,
        config.index.ignore_dirs,
        extra_roots=_registered_extra_roots(config),
    )
    observed: list[ObservedDocument] = []
    for path, bucket in files:
        identity = file_identity(path, repo_root)
        text = read_text_file(path)
        observed.append(
            ObservedDocument(
                workspace_id=workspace_id,
                source_id=bucket or "default",
                document_id=normalize_document_id(identity),
                path=identity,
                content_hash=content_hash(text),
                absolute_path=path,
            )
        )
    return observed


def inventory_for_files(
    config: Config,
    registry: DocumentRegistry,
    rel_paths: Sequence[str],
    *,
    workspace_id: str = "default",
) -> InventoryDiff:
    """Inventory limited to the requested file identities (partial index)."""
    scoped_ids = {
        normalize_document_id(p.replace("\\", "/").lstrip("./"))
        for p in rel_paths
        if p and str(p).strip()
    }
    observed = observe_paths(config, rel_paths, workspace_id=workspace_id)
    return classify_inventory(
        registry,
        observed,
        workspace_id=workspace_id,
        scoped_document_ids=scoped_ids,
    )


def inventory_for_workspace(
    config: Config,
    registry: DocumentRegistry,
    *,
    workspace_id: str = "default",
) -> InventoryDiff:
    observed = observe_workspace(config, workspace_id=workspace_id)
    return classify_inventory(registry, observed, workspace_id=workspace_id)


def chunks_for_observed(
    config: Config,
    items: Iterable[ObservedDocument],
) -> list[dict]:
    """Build chunks for observed documents (paths that still exist)."""
    from rag.indexer.run import build_chunks_for_files

    paths = [item.path for item in items]
    if not paths:
        return []
    return build_chunks_for_files(config, paths)
