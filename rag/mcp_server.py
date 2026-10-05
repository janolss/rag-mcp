"""MCP server exposing RAG tools, resources, and prompts."""

from __future__ import annotations

import logging
import os
import signal

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from rag import mcp_prompts
from rag.config import PACKAGE_ROOT, load_config
from rag.retrieval import search as retrieval
from rag.retrieval.context_pack import get_context_pack as _get_context_pack
from rag.retrieval.impact import find_gaps as _find_gaps
from rag.retrieval.impact import impact_of_change as _impact_of_change
from rag.retrieval.sources_info import list_sources as _list_sources
from rag.retrieval.status_info import index_status as _index_status
from rag.retrieval.trace import trace_requirement as _trace_requirement
from rag.runtime import RagRuntime
from rag.store import QdrantLockError

load_dotenv(PACKAGE_ROOT / ".env")
os.chdir(PACKAGE_ROOT)

logger = logging.getLogger(__name__)

config = load_config(os.environ.get("RAG_CONFIG", "config.yaml"))
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

runtime = RagRuntime(config)

mcp = MCPServer(
    config.mcp.name,
    instructions=config.mcp.instructions,
)


def _with_runtime(search_fn, **kwargs) -> str:
    try:
        store = runtime.get_store()
        embedder = runtime.get_embedder()
    except QdrantLockError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to initialize RAG runtime")
        return f"Error: failed to initialize RAG runtime: {exc}"

    return search_fn(
        config,
        store=store,
        embedder=embedder,
        **kwargs,
    )


@mcp.tool()
def search_knowledge(
    query: str,
    top_k: int | None = None,
    path_prefix: str | None = None,
) -> str:
    """
    Search workspace documentation (README, docs, and configured knowledge sources).

    Use this for architecture, patterns, security, operations, and onboarding questions.
    Results are documentation chunks (typically app=global).

    Args:
        query: Natural-language or keyword query.
        top_k: Optional result count override.
        path_prefix: Optional repo-relative path prefix filter (e.g. docs/requirements/).
    """
    return _with_runtime(
        retrieval.search_knowledge,
        query=query,
        top_k=top_k,
        path_prefix=path_prefix,
    )


@mcp.tool()
def search_code(
    query: str,
    app: str | None = None,
    top_k: int | None = None,
    path_prefix: str | None = None,
) -> str:
    """
    Search application source and tests under configured code globs.

    Args:
        query: Natural-language or keyword query.
        app: Optional app filter matching a configured index.apps name. Omit to search all.
        top_k: Optional result count override.
        path_prefix: Optional repo-relative path prefix filter (e.g. apps/web/).
    """
    return _with_runtime(
        retrieval.search_code,
        query=query,
        app=app,
        top_k=top_k,
        path_prefix=path_prefix,
    )


@mcp.tool()
def index_status() -> str:
    """
    Show index freshness: points count, model, git_sha, stale hints.

    Call before non-trivial change or review work.
    """
    return _index_status(config)


@mcp.tool()
def list_sources() -> str:
    """
    List configured repo_root, apps, knowledge/code globs, and requirement ID patterns.
    """
    return _list_sources(config)


@mcp.tool()
def get_context_pack(
    task: str,
    app: str | None = None,
    top_k_docs: int = 5,
    top_k_code: int = 8,
) -> str:
    """
    Build a structured context pack (docs + code + files to read) for a task.

    Args:
        task: What you are trying to understand or change.
        app: Optional app filter for code search.
        top_k_docs: Max documentation hits.
        top_k_code: Max code/test hits.
    """
    return _with_runtime(
        _get_context_pack,
        task=task,
        app=app,
        top_k_docs=top_k_docs,
        top_k_code=top_k_code,
    )


@mcp.tool()
def trace_requirement(
    requirement: str,
    app: str | None = None,
    top_k: int = 8,
) -> str:
    """
    Trace a requirement ID or requirement text to docs and implementing code/tests.

    Args:
        requirement: Requirement ID (e.g. REQ-123) or natural-language requirement text.
        app: Optional app filter for code/tests.
        top_k: Max hits per section.
    """
    return _with_runtime(
        _trace_requirement,
        requirement=requirement,
        app=app,
        top_k=top_k,
    )


@mcp.tool()
def impact_of_change(
    change: str,
    app: str | None = None,
    path_prefix: str | None = None,
    top_k: int = 8,
) -> str:
    """
    Estimate impact of a change (file path, symbol, feature, or short diff summary).

    Args:
        change: Description of what is changing.
        app: Optional app filter.
        path_prefix: Optional path scope.
        top_k: Max hits per section.
    """
    return _with_runtime(
        _impact_of_change,
        change=change,
        app=app,
        path_prefix=path_prefix,
        top_k=top_k,
    )


@mcp.tool()
def find_gaps(
    area: str,
    app: str | None = None,
    top_k: int = 10,
) -> str:
    """
    Heuristic gaps: documentation without clear code, and code without clear docs.

    Args:
        area: Feature, module, or requirement area to assess.
        app: Optional app filter for code side.
        top_k: Candidate pool size.
    """
    return _with_runtime(
        _find_gaps,
        area=area,
        app=app,
        top_k=top_k,
    )


@mcp.resource("rag://status", mime_type="application/json")
def resource_status() -> str:
    """Index status JSON (same payload as index_status tool)."""
    return _index_status(config)


@mcp.resource("rag://sources", mime_type="application/json")
def resource_sources() -> str:
    """Configured sources JSON (same payload as list_sources tool)."""
    return _list_sources(config)


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


def main() -> None:
    warmup_error = runtime.try_warmup()
    if warmup_error:
        logger.warning(
            "Starting MCP without an open Qdrant connection (%s). "
            "Tools will retry on each call.",
            warmup_error,
        )
    else:
        logger.info(
            "Starting %s MCP server (collection=%s, mode=%s)",
            config.mcp.name,
            config.qdrant.collection,
            config.qdrant.mode,
        )

    def _shutdown(signum: int, _frame) -> None:
        logger.info("Received signal %s; closing Qdrant", signum)
        runtime.close()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            # Signals may be unavailable in some embed contexts
            pass

    mcp.run()


if __name__ == "__main__":
    main()
