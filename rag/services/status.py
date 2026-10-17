"""Concrete StatusService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.indexer.run import status_report
from rag.observability import derive_lifecycle, get_correlation_id
from rag.security.access import AccessDenied, authorize_source, authorize_workspace
from rag.security.http_auth import require_principal
from rag.services.errors import ServiceError
from rag.services.resolve import resolve_workspace_id


class StatusServiceImpl:
    def __init__(self, config: Config):
        self.config = config

    def get_index_status(
        self,
        *,
        workspace_id: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = resolve_workspace_id(self.config, workspace_id, required=False)
        principal = require_principal()
        try:
            if resolved is not None:
                authorize_workspace(principal, resolved)
            if source_id:
                authorize_source(principal, source_id)
        except AccessDenied as exc:
            raise ServiceError(str(exc)) from exc

        report = status_report(self.config)
        report["workspace_id"] = resolved
        if source_id:
            report["source_id"] = source_id
        file_status = report.get("index_status")
        report["lifecycle"] = derive_lifecycle(
            file_status if isinstance(file_status, dict) else None,
            points_count=int(report.get("points_count") or 0),
        )
        report["correlation_id"] = get_correlation_id()
        report["error_count"] = 1 if report.get("lifecycle") == "error" else 0
        if isinstance(file_status, dict):
            report["last_success_at"] = file_status.get("updated_at")
        else:
            report["last_success_at"] = None
        return report
