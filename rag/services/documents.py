"""Concrete DocumentService implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rag.config import Config
from rag.indexer.identity import normalize_document_id
from rag.indexer.source_model import resolve_workspace_sources
from rag.security.access import AccessDenied, authorize_source, authorize_workspace
from rag.security.http_auth import require_principal
from rag.security.paths import (
    SecurePathError,
    assert_within_roots,
    path_security_policy_from_config,
)
from rag.services.errors import ForbiddenError, NotFoundError, ValidationError
from rag.services.resolve import require_workspace


class DocumentServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def get_document(
        self,
        *,
        workspace_id: str | None = None,
        source_id: str,
        document_id: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        if not (source_id or "").strip():
            raise ValidationError("source_id cannot be empty")
        if not (document_id or "").strip():
            raise ValidationError("document_id cannot be empty")
        if start_line is not None and start_line < 1:
            raise ValidationError("start_line must be >= 1")
        if end_line is not None and end_line < 1:
            raise ValidationError("end_line must be >= 1")
        if start_line is not None and end_line is not None and end_line < start_line:
            raise ValidationError("end_line must be >= start_line")

        workspace = require_workspace(self.config, workspace_id)
        principal = require_principal()
        try:
            authorize_workspace(principal, workspace.id)
            authorize_source(principal, source_id)
        except AccessDenied as exc:
            raise ForbiddenError(str(exc)) from exc

        _, sources = resolve_workspace_sources(self.config, workspace_id=workspace.id)
        source = next((s for s in sources if s.id == source_id), None)
        if source is None:
            raise NotFoundError(f"unknown source {source_id!r} in workspace {workspace.id!r}")

        rel = normalize_document_id(document_id.replace("\\", "/").lstrip("./"))
        repo_root = self.config.repo_root_path.resolve()
        source_root = Path(source.root)
        if not source_root.is_absolute():
            source_root = (repo_root / source_root).resolve()
        else:
            source_root = source_root.resolve()

        candidate = Path(rel)
        if candidate.is_absolute():
            path = candidate
        else:
            # Prefer repo-relative identity (legacy/default), then source root.
            repo_candidate = repo_root / rel
            source_candidate = source_root / rel
            if repo_candidate.is_file():
                path = repo_candidate
            elif source_candidate.is_file():
                path = source_candidate
            else:
                path = repo_candidate

        policy = path_security_policy_from_config(self.config)
        roots = [repo_root, source_root]
        try:
            canonical = assert_within_roots(path, roots, policy=policy)
        except SecurePathError as exc:
            raise NotFoundError(f"document path rejected: {exc}") from exc

        if not canonical.is_file():
            raise NotFoundError(f"document {document_id!r} not found in source {source_id!r}")

        text = canonical.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total = len(lines)
        s = 1 if start_line is None else start_line
        e = total if end_line is None else end_line
        s = max(1, min(s, total + 1))
        e = max(0, min(e, total))
        sliced = "".join(lines[s - 1 : e]) if total else ""

        try:
            identity = str(canonical.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            identity = rel

        return {
            "workspace_id": workspace.id,
            "source_id": source_id,
            "document_id": normalize_document_id(identity),
            "path": identity,
            "start_line": s if total else None,
            "end_line": e if total else None,
            "line_count": total,
            "content": sliced,
        }
