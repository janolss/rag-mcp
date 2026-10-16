"""Versioned workspace.yaml loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rag.domain.models import Relationship, Source, Workspace
from rag.workspaces.errors import ManifestNotFoundError, ManifestValidationError

SUPPORTED_SCHEMA_VERSION = 1
RelationshipTypeName = Literal[
    "depends_on",
    "references",
    "implements",
    "documents",
    "tests",
    "shares_contract_with",
]


class ManifestRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    type: str = Field(min_length=1)
    description: str = ""
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    adapter: str = "filesystem"

    @field_validator("id", "path", "type", "adapter")
    @classmethod
    def strip_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be a non-empty string")
        return text

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return str(Path(value))


class ManifestRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1)
    type: RelationshipTypeName
    description: str = ""

    @field_validator("target")
    @classmethod
    def strip_target(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("target cannot be empty")
        return text


class WorkspaceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    roots: list[ManifestRoot] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    relationships: list[ManifestRelationship] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "name")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be a non-empty string")
        return text

    @model_validator(mode="after")
    def validate_semantics(self) -> WorkspaceManifest:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version}; "
                f"supported={SUPPORTED_SCHEMA_VERSION}"
            )
        if not self.roots:
            raise ValueError("roots must contain at least one entry")
        root_ids = [root.id for root in self.roots]
        if len(root_ids) != len(set(root_ids)):
            raise ValueError("roots[].id values must be unique within the workspace")
        return self


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else str(exc)


def parse_manifest_dict(data: dict[str, Any], *, path: str | None = None) -> WorkspaceManifest:
    try:
        return WorkspaceManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestValidationError(_format_validation_error(exc), path=path) from exc


def load_manifest(path: str | Path) -> WorkspaceManifest:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise ManifestNotFoundError(f"manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ManifestValidationError("manifest root must be a mapping", path=str(manifest_path))
    return parse_manifest_dict(raw, path=str(manifest_path))


def manifest_to_workspace(manifest: WorkspaceManifest) -> Workspace:
    sources = tuple(
        Source(
            id=root.id,
            type=root.type,
            root=root.path,
            include=tuple(root.include),
            exclude=tuple(root.exclude),
            adapter=root.adapter,
            description=root.description,
            bucket=_bucket_for_type(root.type),
        )
        for root in manifest.roots
    )
    relationships = tuple(
        Relationship(
            target=rel.target,
            type=rel.type,
            description=rel.description,
        )
        for rel in manifest.relationships
    )
    return Workspace(
        id=manifest.id,
        name=manifest.name,
        description=manifest.description,
        technologies=tuple(manifest.technologies),
        tags=tuple(manifest.tags),
        instructions=tuple(manifest.instructions),
        sources=sources,
        relationships=relationships,
        root_path=sources[0].root if sources else None,
        legacy=False,
    )


def _bucket_for_type(document_type: str) -> str | None:
    mapping = {
        "source_code": "code",
        "test_code": "code",
        "architecture_docs": "knowledge",
        "technical_docs": "knowledge",
        "requirements": "knowledge",
        "policies": "lis",
        "procedures": "lis",
        "configuration": "knowledge",
    }
    return mapping.get(document_type)


def load_manifests(paths: list[str] | tuple[str, ...]) -> list[Workspace]:
    workspaces: list[Workspace] = []
    seen: set[str] = set()
    for raw_path in paths:
        manifest = load_manifest(raw_path)
        if manifest.id in seen:
            raise ManifestValidationError(
                f"duplicate workspace id across manifests: {manifest.id}",
                path=raw_path,
            )
        seen.add(manifest.id)
        workspaces.append(manifest_to_workspace(manifest))
    return workspaces
