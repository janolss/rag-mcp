"""Index status formatting for MCP tools/resources."""

from __future__ import annotations

import json

from rag.config import Config
from rag.indexer.run import status_report
from rag.store import QdrantLockError


def index_status(config: Config) -> str:
    try:
        report = status_report(config)
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: failed to read index status: {exc}"
    return json.dumps(report, indent=2) + "\n"
