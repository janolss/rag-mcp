"""Local dashboard and background indexing endpoints."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from rag.config import Config
from rag.indexer.jobs import jobs_db_path, run_index_job
from rag.indexer.run import read_status
from rag.indexer.status_store import StatusStore
from rag.security.access import is_loopback_host
from rag.security.http_auth import require_principal
from rag.services import ServiceApp
from rag.version import package_version

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / "gui"


def _access_error(request: Request) -> JSONResponse | None:
    peer = request.client.host if request.client else ""
    try:
        host = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
    except ValueError:
        host = ""
    principal = require_principal()
    if not is_loopback_host(peer) or not is_loopback_host(host):
        return JSONResponse(
            {"error": "The dashboard is available only on localhost"}, status_code=403
        )
    if (principal.workspace_allowlist and "*" not in principal.workspace_allowlist) or (
        principal.source_allowlist and "*" not in principal.source_allowlist
    ):
        return JSONResponse(
            {"error": "The dashboard requires unrestricted access"}, status_code=403
        )
    return None


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    return origin == f"{request.url.scheme}://{request.headers.get('host', '')}"


class Dashboard:
    def __init__(self, config: Config, services: ServiceApp):
        self.config = config
        self.services = services
        self.started_at = time.monotonic()
        self.lock = threading.Lock()
        self.active_job: str | None = None

    def status(self) -> dict[str, Any]:
        try:
            index = self.services.status.get_index_status()
            index_error = None
        except Exception as exc:
            logger.exception("Dashboard could not read index status")
            index = None
            index_error = str(exc)
        return {
            "server": {
                "status": "ok",
                "name": self.config.mcp.name,
                "version": package_version(),
                "uptime_seconds": int(time.monotonic() - self.started_at),
            },
            "index": index,
            "index_error": index_error,
            "reindex_available": self.config.qdrant.mode != "memory",
        }

    def history(self) -> dict[str, Any]:
        workspaces = self.services.workspaces.list_workspaces()
        store = StatusStore(jobs_db_path(self.config))
        store.expire_stale_leases()
        jobs = store.list_jobs()
        last_success: dict[str, float] = {}
        entries = []
        for job in sorted(jobs, key=lambda item: item.updated_at, reverse=True):
            result = job.result() or {}
            ids = result.get("workspace_ids") or (
                [job.workspace_id] if job.workspace_id != "*" else []
            )
            if job.status == "succeeded":
                for workspace_id in ids:
                    last_success[workspace_id] = max(
                        last_success.get(workspace_id, 0), job.updated_at
                    )
            entries.append(
                {
                    "job_id": job.job_id,
                    "workspace_id": job.workspace_id,
                    "status": job.status,
                    "updated_at": job.updated_at,
                    "duration_seconds": (
                        job.updated_at - job.created_at
                        if job.idempotency_key.startswith("gui-")
                        and job.status in {"succeeded", "failed", "cancelled"}
                        else None
                    ),
                    "error": job.error or None,
                }
            )

        # Older indexing runs may only have the shared status file, not a job.
        status = read_status(self.config)
        if status and status.get("updated_at"):
            from datetime import datetime

            updated = datetime.fromisoformat(
                status["updated_at"].replace("Z", "+00:00")
            ).timestamp()
            for workspace_id in status.get("workspace_ids") or (
                [status["workspace_id"]] if status.get("workspace_id") else []
            ):
                last_success[workspace_id] = max(last_success.get(workspace_id, 0), updated)
        return {
            "workspaces": [
                {"id": ws["id"], "name": ws["name"], "last_success_at": last_success.get(ws["id"])}
                for ws in workspaces
            ],
            "jobs": entries[:100],
        }

    def submit(self, workspace_id: str | None) -> dict[str, Any] | None:
        with self.lock:
            if self.active_job is not None:
                return None
            store = StatusStore(jobs_db_path(self.config))
            store.expire_stale_leases()
            if any(job.status in {"queued", "running"} for job in store.list_jobs()):
                return None
            key = f"gui-{uuid.uuid4()}"
            submitted = run_index_job(
                self.config, workspace_id=workspace_id or "*", wait=False, idempotency_key=key
            )["job"]
            self.active_job = submitted["job_id"]

            def execute() -> None:
                try:
                    run_index_job(
                        self.config, workspace_id=workspace_id or "*", idempotency_key=key
                    )
                except Exception as exc:
                    logger.exception("Dashboard index job %s failed", submitted["job_id"])
                    job = store.get(submitted["job_id"])
                    if job and job.status in {"queued", "running"}:
                        store.update(job.job_id, status="failed", clear_lease=True, error=str(exc))
                finally:
                    with self.lock:
                        self.active_job = None

            thread = threading.Thread(target=execute, name="rag-gui-index", daemon=True)
            try:
                thread.start()
            except Exception:
                self.active_job = None
                store.update(
                    submitted["job_id"],
                    status="failed",
                    clear_lease=True,
                    error="Failed to start index worker",
                )
                raise
            return submitted


def build_gui_routes(config: Config, services: ServiceApp) -> list[Route]:
    dashboard = Dashboard(config, services)

    async def asset(request: Request) -> Response:
        if error := _access_error(request):
            return error
        name = request.path_params.get("name", "index.html")
        if name not in {"index.html", "app.js", "style.css"}:
            return Response(status_code=404)
        return FileResponse(
            ASSETS / name,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def status(request: Request) -> Response:
        if error := _access_error(request):
            return error
        return JSONResponse(await run_in_threadpool(dashboard.status))

    async def history(request: Request) -> Response:
        if error := _access_error(request):
            return error
        try:
            return JSONResponse(await run_in_threadpool(dashboard.history))
        except Exception:
            logger.exception("Dashboard could not read indexing history")
            return JSONResponse({"error": "Could not read indexing history"}, status_code=500)

    async def reindex(request: Request) -> Response:
        if error := _access_error(request):
            return error
        if not _same_origin(request):
            return JSONResponse({"error": "A same-origin request is required"}, status_code=403)
        if config.qdrant.mode == "memory":
            return JSONResponse(
                {"error": "Reindexing requires Qdrant local or server mode"}, status_code=400
            )
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse({"error": "Content-Type must be application/json"}, status_code=415)
        try:
            data = await request.json()
        except ValueError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        if not isinstance(data, dict) or set(data) - {"workspace_id"}:
            return JSONResponse({"error": "Expected an object with workspace_id"}, status_code=400)
        workspace_id = data.get("workspace_id")
        if workspace_id is not None and (
            not isinstance(workspace_id, str) or not workspace_id.strip() or workspace_id == "*"
        ):
            return JSONResponse({"error": "Invalid workspace_id"}, status_code=400)
        try:
            workspaces = await run_in_threadpool(services.workspaces.list_workspaces)
            if not workspaces:
                return JSONResponse({"error": "No workspaces are registered"}, status_code=400)
            if workspace_id is not None and workspace_id not in {ws["id"] for ws in workspaces}:
                return JSONResponse({"error": "Workspace not found"}, status_code=404)
            job = await run_in_threadpool(dashboard.submit, workspace_id)
        except Exception:
            logger.exception("Dashboard could not start indexing")
            return JSONResponse(
                {"error": "Could not start indexing; check server logs"}, status_code=500
            )
        if job is None:
            return JSONResponse({"error": "An indexing job is already active"}, status_code=409)
        return JSONResponse({"job_id": job["job_id"], "status": job["status"]}, status_code=202)

    return [
        Route("/gui", asset, methods=["GET"]),
        Route("/gui/", asset, methods=["GET"]),
        Route("/gui/status", status, methods=["GET"]),
        Route("/gui/indexing-history", history, methods=["GET"]),
        Route("/gui/reindex", reindex, methods=["POST"]),
        Route("/gui/{name}", asset, methods=["GET"]),
    ]
