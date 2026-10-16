"""Concrete StatusService implementation."""

from __future__ import annotations

from typing import Any

from rag.config import Config
from rag.indexer.run import status_report
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
        report = status_report(self.config)
        report["workspace_id"] = resolved
        if source_id:
            report["source_id"] = source_id
        return report
