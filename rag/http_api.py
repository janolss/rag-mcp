"""Starlette routes for /api/v1 with service-layer parity to MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from rag.config import Config
from rag.http_schemas import SearchRequest
from rag.observability import (
    METRICS,
    correlation_scope,
    get_correlation_id,
    new_correlation_id,
)
from rag.services import (
    NotFoundError,
    ServiceApp,
    ServiceError,
    ValidationError,
    WorkspaceRequiredError,
)
from rag.version import package_version

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "x-correlation-id"


def _error_response(exc: Exception, *, status: int | None = None) -> JSONResponse:
    if isinstance(exc, NotFoundError):
        code, http_status = "not_found", 404
    elif isinstance(exc, WorkspaceRequiredError):
        code, http_status = "workspace_required", 400
    elif isinstance(exc, (ValidationError, PydanticValidationError)):
        code, http_status = "validation_error", 400
    elif isinstance(exc, ServiceError):
        code, http_status = "service_error", 400
    else:
        logger.exception("Unhandled API error")
        code, http_status = "internal_error", 500
    if status is not None:
        http_status = status
    return JSONResponse({"error": str(exc), "code": code}, status_code=http_status)


def build_api_routes(config: Config, services: ServiceApp | None = None) -> list[Route]:
    """Return /api/v1 routes bound to the shared service layer."""
    app_services = services or ServiceApp(config)

    async def api_root(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": config.mcp.name,
                "version": package_version(),
                "api": "v1",
                "endpoints": [
                    "GET /api/v1/workspaces",
                    "GET /api/v1/workspaces/{workspace_id}",
                    "GET /api/v1/workspaces/{workspace_id}/sources",
                    "POST /api/v1/search",
                    "GET /api/v1/documents",
                    "GET /api/v1/index/status",
                ],
            }
        )

    async def list_workspaces(request: Request) -> JSONResponse:
        query = request.query_params.get("query")
        tags = request.query_params.getlist("tag") or None
        try:
            payload = app_services.workspaces.list_workspaces(query=query, tags=tags)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(payload)

    async def get_workspace(request: Request) -> JSONResponse:
        workspace_id = request.path_params["workspace_id"]
        try:
            payload = app_services.workspaces.get_workspace(workspace_id)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(payload)

    async def list_sources(request: Request) -> JSONResponse:
        workspace_id = request.path_params["workspace_id"]
        try:
            payload = app_services.sources.list_sources(workspace_id)
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(payload)

    async def search(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            req = SearchRequest.model_validate(body)
            hits = app_services.search.search(
                workspace_id=req.workspace_id,
                query=req.query,
                source_ids=req.source_ids,
                document_types=req.document_types,
                limit=req.limit,
                scope=req.scope,
                search_mode=req.search_mode,
                path_prefix=req.path_prefix,
            )
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse({"hits": hits})

    async def get_document(request: Request) -> JSONResponse:
        params = request.query_params
        source_id = params.get("source_id")
        document_id = params.get("document_id")
        if not source_id or not document_id:
            return _error_response(
                ValidationError("source_id and document_id are required"),
                status=400,
            )
        start_raw = params.get("start_line")
        end_raw = params.get("end_line")
        try:
            start_line = int(start_raw) if start_raw is not None else None
            end_line = int(end_raw) if end_raw is not None else None
            payload = app_services.documents.get_document(
                workspace_id=params.get("workspace_id"),
                source_id=source_id,
                document_id=document_id,
                start_line=start_line,
                end_line=end_line,
            )
        except Exception as exc:
            return _error_response(exc)
        return JSONResponse(payload)

    async def index_status(request: Request) -> JSONResponse:
        params = request.query_params
        try:
            with METRICS.timer("rag_index_status_latency_seconds"):
                payload = app_services.status.get_index_status(
                    workspace_id=params.get("workspace_id"),
                    source_id=params.get("source_id"),
                )
            METRICS.incr("rag_index_status_total")
        except Exception as exc:
            return _error_response(exc)
        return _json_with_correlation(payload)

    async def health(_request: Request) -> JSONResponse:
        return _json_with_correlation({"status": "ok"})

    async def ready(_request: Request) -> JSONResponse:
        try:
            report = app_services.status.get_index_status()
            lifecycle = report.get("lifecycle")
            ready_ok = lifecycle in {"ready", "partial"}
            body = {
                "ready": ready_ok,
                "lifecycle": lifecycle,
                "workspace_id": report.get("workspace_id"),
            }
            return _json_with_correlation(body, status=200 if ready_ok else 503)
        except Exception as exc:
            return _error_response(exc)

    async def metrics(_request: Request) -> JSONResponse:
        from starlette.responses import PlainTextResponse

        return PlainTextResponse(
            METRICS.render_prometheus(),
            media_type="text/plain; version=0.0.4",
            headers={CORRELATION_HEADER: get_correlation_id() or new_correlation_id()},
        )

    return [
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/ready", endpoint=ready, methods=["GET"]),
        Route("/metrics", endpoint=metrics, methods=["GET"]),
        Route("/api/v1", endpoint=api_root, methods=["GET"]),
        Route("/api/v1/workspaces", endpoint=list_workspaces, methods=["GET"]),
        Route(
            "/api/v1/workspaces/{workspace_id}",
            endpoint=get_workspace,
            methods=["GET"],
        ),
        Route(
            "/api/v1/workspaces/{workspace_id}/sources",
            endpoint=list_sources,
            methods=["GET"],
        ),
        Route("/api/v1/search", endpoint=search, methods=["POST"]),
        Route("/api/v1/documents", endpoint=get_document, methods=["GET"]),
        Route("/api/v1/index/status", endpoint=index_status, methods=["GET"]),
    ]


def _json_with_correlation(payload: Any, *, status: int = 200) -> JSONResponse:
    cid = get_correlation_id() or new_correlation_id()
    return JSONResponse(
        payload,
        status_code=status,
        headers={CORRELATION_HEADER: cid},
    )


class CorrelationMiddleware:
    """Propagate/generate X-Correlation-ID for each request."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        incoming = headers.get(CORRELATION_HEADER) or new_correlation_id()
        with correlation_scope(incoming):
            await self.app(scope, receive, send)


def mount_api_routes(app: Any, config: Config, services: ServiceApp | None = None) -> None:
    """Insert /api/v1 routes onto an existing Starlette app (MCP HTTP host)."""
    for route in reversed(build_api_routes(config, services=services)):
        app.routes.insert(0, route)


def create_api_app(config: Config, services: ServiceApp | None = None) -> Starlette:
    """Standalone Starlette app exposing only /api/v1 (useful for tests)."""
    app = Starlette(routes=build_api_routes(config, services=services))
    app.add_middleware(CorrelationMiddleware)
    return app


def create_api_mount(config: Config, services: ServiceApp | None = None) -> Mount:
    """Optional mount helper for embedding under another root."""
    return Mount("/", app=create_api_app(config, services=services))
