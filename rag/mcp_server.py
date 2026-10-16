"""MCP server exposing RAG tools, resources, and prompts."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from collections.abc import Callable
from typing import Any

import anyio
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from rag import mcp_prompts
from rag.config import (
    PACKAGE_ROOT,
    Config,
    load_config,
    mcp_public_url,
    normalize_mcp_transport,
    resolve_mcp_instructions,
)
from rag.mcp_http import endpoint_urls, run_http
from rag.mcp_results import as_tool_result, tool_error
from rag.mcp_validate import (
    require_nonempty,
    validate_lis_filters,
    validate_top_k,
)
from rag.retrieval import search as retrieval
from rag.retrieval.context_pack import get_context_pack as _get_context_pack
from rag.retrieval.impact import find_gaps as _find_gaps
from rag.retrieval.impact import impact_of_change as _impact_of_change
from rag.retrieval.sources_info import list_sources as _list_sources
from rag.retrieval.sources_info import list_sources_resource as _list_sources_resource
from rag.retrieval.status_info import index_status as _index_status
from rag.retrieval.status_info import index_status_resource as _index_status_resource
from rag.retrieval.trace import trace_requirement as _trace_requirement
from rag.runtime import RagRuntime
from rag.services import (
    NotFoundError,
    ServiceApp,
    ServiceError,
    ValidationError,
)
from rag.store import QdrantLockError
from rag.version import package_version

logger = logging.getLogger(__name__)

_SERVER_TITLE = "Workspace RAG"
_SERVER_DESCRIPTION = (
    "Local retrieval for coding agents: search docs/code/LIS, context packs, "
    "requirement tracing, impact analysis, and review prompts."
)


def create_mcp_server(config: Config, runtime: RagRuntime | None = None) -> MCPServer:
    """Build an MCPServer with tools/prompts registered per capabilities."""
    rt = runtime or RagRuntime(config)
    instructions = resolve_mcp_instructions(config)
    server = MCPServer(
        config.mcp.name,
        title=_SERVER_TITLE,
        description=_SERVER_DESCRIPTION,
        instructions=instructions,
        version=package_version(),
    )
    _register(server, config, rt)
    return server


def _register(mcp: MCPServer, config: Config, runtime: RagRuntime) -> None:
    caps = config.mcp.capabilities
    services = ServiceApp(config)

    def _service_error(exc: Exception) -> CallToolResult:
        if isinstance(exc, (ValidationError, NotFoundError, ServiceError)):
            return tool_error(str(exc))
        logger.exception("RAG service call failed")
        return tool_error(str(exc))

    async def _with_runtime(search_fn: Callable[..., str], **kwargs: Any) -> CallToolResult:
        try:
            store = runtime.get_store()
            embedder = runtime.get_embedder()
        except QdrantLockError as exc:
            return tool_error(str(exc))
        except Exception as exc:
            logger.exception("Failed to initialize RAG runtime")
            return tool_error(f"failed to initialize RAG runtime: {exc}")

        def _call() -> str:
            return search_fn(
                config,
                store=store,
                embedder=embedder,
                **kwargs,
            )

        try:
            text = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            logger.exception("RAG tool call failed")
            return tool_error(str(exc))
        return as_tool_result(text)

    async def _with_search_service(method: Callable[..., Any], **kwargs: Any) -> CallToolResult:
        try:
            store = runtime.get_store()
            embedder = runtime.get_embedder()
        except QdrantLockError as exc:
            return tool_error(str(exc))
        except Exception as exc:
            logger.exception("Failed to initialize RAG runtime")
            return tool_error(f"failed to initialize RAG runtime: {exc}")

        app = services.with_runtime(store=store, embedder=embedder)

        def _call() -> Any:
            return method(app, **kwargs)

        try:
            payload = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            return _service_error(exc)
        return as_tool_result(json.dumps(payload, indent=2) + "\n")

    if caps.knowledge:

        @mcp.tool()
        async def search_knowledge(
            query: str,
            top_k: int | None = None,
            path_prefix: str | None = None,
        ) -> CallToolResult:
            """
            Search workspace documentation (README, docs, and configured knowledge sources).

            Use this for architecture, patterns, security, operations, and onboarding questions.
            Results are documentation chunks (typically app=global). Not for org-wide LIS/governance.

            Args:
                query: Natural-language or keyword query.
                top_k: Optional result count override.
                path_prefix: Optional repo-relative path prefix filter (e.g. docs/requirements/).
            """
            if err := require_nonempty("query", query):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            return await _with_runtime(
                retrieval.search_knowledge,
                query=query,
                top_k=top_k,
                path_prefix=path_prefix,
            )

    if caps.code:

        @mcp.tool()
        async def search_code(
            query: str,
            app: str | None = None,
            top_k: int | None = None,
            path_prefix: str | None = None,
        ) -> CallToolResult:
            """
            Search application source and tests under configured code globs.

            Args:
                query: Natural-language or keyword query.
                app: Optional app filter matching a configured index.apps name. Omit to search all.
                top_k: Optional result count override.
                path_prefix: Optional repo-relative path prefix filter (e.g. apps/web/).
            """
            if err := require_nonempty("query", query):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            return await _with_runtime(
                retrieval.search_code,
                query=query,
                app=app,
                top_k=top_k,
                path_prefix=path_prefix,
            )

    if caps.lis:

        @mcp.tool()
        async def search_lis(
            query: str,
            top_k: int | None = None,
            path_prefix: str | None = None,
            doc_type: str | None = None,
            process_area: str | None = None,
            domain: str | None = None,
            status: str | None = None,
        ) -> CallToolResult:
            """
            Search organizational LIS / ledningssystem documents (policies, riktlinjer, anvisningar, etc.).

            Use for governance that applies across the organization, not workspace-specific technical docs.
            Prefer status=approved. Binding order: policy > riktlinje > anvisning > instruktion > mall.

            Args:
                query: Natural-language or keyword query.
                top_k: Optional result count override.
                path_prefix: Optional path prefix filter.
                doc_type: Optional filter (policy|riktlinje|anvisning|instruktion|mall|...).
                process_area: Optional filter (ledning|behov|planera|utveckla|leverera|stod).
                domain: Optional domain filter (infosec|kvalitet|mtp|...).
                status: Optional status filter (approved|draft).
            """
            if err := require_nonempty("query", query):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            if err := validate_lis_filters(
                doc_type=doc_type,
                process_area=process_area,
                status=status,
            ):
                return tool_error(err)
            return await _with_runtime(
                retrieval.search_lis,
                query=query,
                top_k=top_k,
                path_prefix=path_prefix,
                doc_type=doc_type,
                process_area=process_area,
                domain=domain,
                status=status,
            )

    @mcp.tool()
    async def list_workspaces(
        query: str | None = None,
        tags: list[str] | None = None,
    ) -> CallToolResult:
        """
        List registered workspaces (id, name, tags, source counts).

        Args:
            query: Optional name/id substring filter.
            tags: Optional tag allowlist (workspace must include all).
        """

        def _call() -> list[dict[str, Any]]:
            return services.workspaces.list_workspaces(query=query, tags=tags)

        try:
            payload = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            return _service_error(exc)
        return as_tool_result(json.dumps(payload, indent=2) + "\n")

    @mcp.tool()
    async def get_workspace_info(workspace_id: str) -> CallToolResult:
        """
        Return detailed metadata for one workspace, including sources and relationships.

        Args:
            workspace_id: Stable workspace id (use list_workspaces to discover).
        """
        if err := require_nonempty("workspace_id", workspace_id):
            return tool_error(err)

        def _call() -> dict[str, Any]:
            return services.workspaces.get_workspace(workspace_id)

        try:
            payload = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            return _service_error(exc)
        return as_tool_result(json.dumps(payload, indent=2) + "\n")

    @mcp.tool()
    async def get_index_status(
        workspace_id: str | None = None,
        source_id: str | None = None,
    ) -> CallToolResult:
        """
        Structured index status for an optional workspace/source scope.

        Prefer this over the legacy index_status tool for multi-workspace setups.

        Args:
            workspace_id: Optional workspace id (inferred when only default exists).
            source_id: Optional source id annotation.
        """

        def _call() -> dict[str, Any]:
            return services.status.get_index_status(
                workspace_id=workspace_id,
                source_id=source_id,
            )

        try:
            payload = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            return _service_error(exc)
        return as_tool_result(json.dumps(payload, indent=2) + "\n")

    @mcp.tool()
    async def index_status() -> CallToolResult:
        """
        Show index freshness: points count, model, git_sha, stale hints.

        Legacy wrapper; prefer get_index_status for workspace-scoped clients.
        Call before non-trivial change or review work.
        """
        text = await anyio.to_thread.run_sync(_index_status, config)
        return as_tool_result(text)

    @mcp.tool()
    async def list_sources(workspace_id: str | None = None) -> CallToolResult:
        """
        List sources for a workspace, or legacy config summary when workspace_id is omitted.

        Args:
            workspace_id: Optional workspace id. When set, returns that workspace's sources only.
        """
        if workspace_id:

            def _call_ws() -> list[dict[str, Any]]:
                return services.sources.list_sources(workspace_id)

            try:
                payload = await anyio.to_thread.run_sync(_call_ws)
            except Exception as exc:
                return _service_error(exc)
            return as_tool_result(json.dumps(payload, indent=2) + "\n")

        text = await anyio.to_thread.run_sync(_list_sources, config)
        return as_tool_result(text)

    @mcp.tool()
    async def search(
        query: str,
        workspace_id: str | None = None,
        source_ids: list[str] | None = None,
        document_types: list[str] | None = None,
        limit: int | None = None,
        scope: str = "workspace",
        search_mode: str = "semantic",
        path_prefix: str | None = None,
    ) -> CallToolResult:
        """
        Workspace-scoped search via the application service layer.

        Args:
            query: Natural-language or keyword query.
            workspace_id: Required when multiple workspaces are registered.
            source_ids: Optional single-source allowlist.
            document_types: Optional payload type filters (documentation|code|test|lis).
            limit: Max hits (1-50).
            scope: workspace (default) or source.
            search_mode: semantic (keyword/hybrid arrive in a later phase).
            path_prefix: Optional repo-relative path prefix filter.
        """
        if err := require_nonempty("query", query):
            return tool_error(err)
        if err := validate_top_k(limit):
            return tool_error(err)
        return await _with_search_service(
            lambda app, **kw: app.search.search(**kw),
            query=query,
            workspace_id=workspace_id,
            source_ids=source_ids,
            document_types=document_types,
            limit=limit,
            scope=scope,
            search_mode=search_mode,
            path_prefix=path_prefix,
        )

    @mcp.tool()
    async def get_document(
        source_id: str,
        document_id: str,
        workspace_id: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> CallToolResult:
        """
        Read a registered document (optionally a line range) under path security rules.

        Args:
            source_id: Source id from list_sources / get_workspace_info.
            document_id: Stable document id (usually repo-relative path).
            workspace_id: Required when multiple workspaces are registered.
            start_line: Optional 1-based start line.
            end_line: Optional 1-based inclusive end line.
        """
        if err := require_nonempty("source_id", source_id):
            return tool_error(err)
        if err := require_nonempty("document_id", document_id):
            return tool_error(err)

        def _call() -> dict[str, Any]:
            return services.documents.get_document(
                workspace_id=workspace_id,
                source_id=source_id,
                document_id=document_id,
                start_line=start_line,
                end_line=end_line,
            )

        try:
            payload = await anyio.to_thread.run_sync(_call)
        except Exception as exc:
            return _service_error(exc)
        return as_tool_result(json.dumps(payload, indent=2) + "\n")

    if caps.knowledge or caps.code or caps.lis:

        @mcp.tool()
        async def get_context_pack(
            task: str,
            app: str | None = None,
            top_k_docs: int = 5,
            top_k_code: int = 8,
            top_k_lis: int = 5,
        ) -> CallToolResult:
            """
            Build a structured context pack for a task from enabled sources (docs / code / LIS).

            Args:
                task: What you are trying to understand or change.
                app: Optional app filter for code search.
                top_k_docs: Max documentation hits.
                top_k_code: Max code/test hits.
                top_k_lis: Max LIS hits.
            """
            if err := require_nonempty("task", task):
                return tool_error(err)
            for name, value in (
                ("top_k_docs", top_k_docs),
                ("top_k_code", top_k_code),
                ("top_k_lis", top_k_lis),
            ):
                if err := validate_top_k(value, name=name):
                    return tool_error(err)
            return await _with_runtime(
                _get_context_pack,
                task=task,
                app=app,
                top_k_docs=top_k_docs,
                top_k_code=top_k_code,
                top_k_lis=top_k_lis,
            )

    if caps.knowledge or caps.code:

        @mcp.tool()
        async def trace_requirement(
            requirement: str,
            app: str | None = None,
            top_k: int = 8,
        ) -> CallToolResult:
            """
            Trace a requirement ID or requirement text to docs and implementing code/tests.

            Args:
                requirement: Requirement ID (e.g. REQ-123) or natural-language requirement text.
                app: Optional app filter for code/tests.
                top_k: Max hits per section.
            """
            if err := require_nonempty("requirement", requirement):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            return await _with_runtime(
                _trace_requirement,
                requirement=requirement,
                app=app,
                top_k=top_k,
            )

        @mcp.tool()
        async def impact_of_change(
            change: str,
            app: str | None = None,
            path_prefix: str | None = None,
            top_k: int = 8,
        ) -> CallToolResult:
            """
            Estimate impact of a change (file path, symbol, feature, or short diff summary).

            Args:
                change: Description of what is changing.
                app: Optional app filter.
                path_prefix: Optional path scope.
                top_k: Max hits per section.
            """
            if err := require_nonempty("change", change):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            return await _with_runtime(
                _impact_of_change,
                change=change,
                app=app,
                path_prefix=path_prefix,
                top_k=top_k,
            )

        @mcp.tool()
        async def find_gaps(
            area: str,
            app: str | None = None,
            top_k: int = 10,
        ) -> CallToolResult:
            """
            Heuristic gaps: documentation without clear code, and code without clear docs.

            Args:
                area: Feature, module, or requirement area to assess.
                app: Optional app filter for code side.
                top_k: Candidate pool size.
            """
            if err := require_nonempty("area", area):
                return tool_error(err)
            if err := validate_top_k(top_k):
                return tool_error(err)
            return await _with_runtime(
                _find_gaps,
                area=area,
                app=app,
                top_k=top_k,
            )

    @mcp.resource("rag://status", mime_type="application/json")
    def resource_status() -> str:
        """Index status JSON (same payload as index_status tool, with ok envelope)."""
        return _index_status_resource(config)

    @mcp.resource("rag://sources", mime_type="application/json")
    def resource_sources() -> str:
        """Configured sources JSON (same payload as list_sources tool, with ok envelope)."""
        return _list_sources_resource(config)

    if caps.knowledge or caps.code:

        @mcp.prompt(name="change-plan", description="Plan a code change using RAG tools")
        def change_plan(task: str, app: str = "") -> str:
            return mcp_prompts.change_plan_text(task, app)

        @mcp.prompt(name="pr-review", description="Review a change against requirements/docs")
        def pr_review(change_summary: str, app: str = "") -> str:
            return mcp_prompts.pr_review_text(change_summary, app)

        @mcp.prompt(
            name="requirement-coverage",
            description="Assess requirement coverage in code and docs",
        )
        def requirement_coverage(requirement: str, app: str = "") -> str:
            return mcp_prompts.requirement_coverage_text(requirement, app)

        @mcp.prompt(name="onboarding-slice", description="Reading guide for a topic/app area")
        def onboarding_slice(topic: str, app: str = "") -> str:
            return mcp_prompts.onboarding_slice_text(topic, app)

        @mcp.prompt(
            name="regression-check",
            description="Identify likely regressions for a changed area",
        )
        def regression_check(changed_area: str, app: str = "") -> str:
            return mcp_prompts.regression_check_text(changed_area, app)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workspace RAG MCP server")
    parser.add_argument(
        "--config",
        default=os.environ.get("RAG_CONFIG", "config.yaml"),
        help="Path to config.yaml (relative to package root unless absolute)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse", "http", "both", "dual"],
        default=None,
        help="stdio | streamable-http (/mcp) | sse | http (both /mcp and /sse)",
    )
    parser.add_argument("--host", default=None, help="HTTP bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="HTTP bind port (default 8000)")
    parser.add_argument(
        "--path",
        default=None,
        help="HTTP mount path (default /mcp or /sse depending on transport)",
    )
    return parser


def apply_cli_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    """Apply CLI transport flags onto an already-loaded config (mutates mcp)."""
    if args.transport is not None:
        cfg.mcp.transport = normalize_mcp_transport(args.transport)
    if args.host is not None:
        cfg.mcp.host = args.host.strip() or cfg.mcp.host
    if args.port is not None:
        cfg.mcp.port = int(args.port)
    if args.path is not None:
        cfg.mcp.path = args.path.strip()
    return cfg


def _configure_logging(cfg: Config) -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> None:
    load_dotenv(PACKAGE_ROOT / ".env")
    os.chdir(PACKAGE_ROOT)

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    config = load_config(args.config)
    _configure_logging(config)
    apply_cli_overrides(config, args)

    runtime = RagRuntime(config)
    mcp = create_mcp_server(config, runtime)

    warmup_error = runtime.try_warmup()
    url = mcp_public_url(config)
    if warmup_error:
        logger.warning(
            "Starting MCP without an open Qdrant connection (%s). Tools will retry on each call.",
            warmup_error,
        )
    else:
        logger.info(
            "Starting %s MCP server v%s (collection=%s, mode=%s, transport=%s, capabilities=%s%s)",
            config.mcp.name,
            package_version(),
            config.qdrant.collection,
            config.qdrant.mode,
            config.mcp.transport,
            {
                "knowledge": config.mcp.capabilities.knowledge,
                "code": config.mcp.capabilities.code,
                "lis": config.mcp.capabilities.lis,
            },
            f", url={url}" if url else "",
        )

    transport = normalize_mcp_transport(config.mcp.transport)
    if transport != "stdio":
        if config.mcp.host in {"0.0.0.0", "::", "[::]"}:
            logger.warning(
                "MCP HTTP is bound to %s without authentication. "
                "Prefer 127.0.0.1 for local use, or put a reverse proxy with auth in front.",
                config.mcp.host,
            )
        urls = endpoint_urls(config)
        print("MCP HTTP endpoints:", file=sys.stderr)
        for kind, endpoint in urls.items():
            print(f"  {kind}: {endpoint}", file=sys.stderr)
        if "streamable-http" in urls:
            print(
                f"→ Prefer for modern URL clients: {urls['streamable-http']}",
                file=sys.stderr,
            )
        elif url:
            print(f"→ SSE clients: GET {url} (POST messages to /messages/)", file=sys.stderr)

    def _shutdown(signum: int, _frame) -> None:
        logger.info("Received signal %s; closing Qdrant", signum)
        runtime.close()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            # Signals may be unavailable in some embed contexts
            pass

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        run_http(mcp, config)


if __name__ == "__main__":
    main()
