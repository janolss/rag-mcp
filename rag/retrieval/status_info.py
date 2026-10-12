"""Index status formatting for MCP tools/resources."""

from __future__ import annotations

import json

from rag.config import Config
from rag.indexer.run import status_report
from rag.mcp_results import resource_error, resource_ok
from rag.store import QdrantLockError


def index_status(config: Config) -> str:
    try:
        report = status_report(config)
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: failed to read index status: {exc}"
    return json.dumps(report, indent=2) + "\n"


def index_status_resource(config: Config) -> str:
    try:
        report = status_report(config)
    except QdrantLockError as exc:
        return resource_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        return resource_error(f"failed to read index status: {exc}")
    return resource_ok(report)
