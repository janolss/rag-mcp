"""Stable domain objects for workspaces, sources, documents and relationships."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceStatus = Literal["not_indexed", "indexing", "ready", "partial", "error"]
RelationshipType = Literal[
    "depends_on",
    "references",
    "implements",
    "documents",
    "tests",
    "shares_contract_with",
]


@dataclass(frozen=True)
class Relationship:
    """Directed relationship from the owning workspace to a target workspace."""

    target: str
    type: RelationshipType
    description: str = ""


@dataclass(frozen=True)
class Source:
    """Explicit knowledge source within a workspace."""

    id: str
    type: str
    root: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    adapter: str = "filesystem"
    status: SourceStatus = "not_indexed"
    description: str = ""
    bucket: str | None = None


@dataclass(frozen=True)
class DocumentRef:
    """Logical document identity independent of content hash."""

    workspace_id: str
    source_id: str
    document_id: str
    path: str
    document_type: str
    language: str | None = None


@dataclass(frozen=True)
class ChunkIdentity:
    """Stable chunk key within a document."""

    workspace_id: str
    source_id: str
    document_id: str
    chunk_key: str
    chunk_index: int = 0


@dataclass(frozen=True)
class Workspace:
    """Registered workspace with stable ID and metadata."""

    id: str
    name: str
    description: str = ""
    technologies: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    root_path: str | None = None
    legacy: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def source_by_id(self, source_id: str) -> Source | None:
        for source in self.sources:
            if source.id == source_id:
                return source
        return None
