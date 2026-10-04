"""FastMCP server exposing search_knowledge and search_code."""

from __future__ import annotations

import logging
import os
import signal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from rag.config import PACKAGE_ROOT, load_config
from rag.retrieval import search as retrieval
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

mcp = FastMCP(
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
def search_knowledge(query: str, top_k: int | None = None) -> str:
    """
    Search workspace documentation (README, docs, and configured knowledge sources).

    Use this for architecture, patterns, security, operations, and onboarding questions.
    Results are documentation chunks (typically app=global).

    Args:
        query: Natural-language or keyword query.
        top_k: Optional result count override.
    """
    return _with_runtime(retrieval.search_knowledge, query=query, top_k=top_k)


@mcp.tool()
def search_code(query: str, app: str | None = None, top_k: int | None = None) -> str:
    """
    Search application source and tests under configured code globs.

    Args:
        query: Natural-language or keyword query.
        app: Optional app filter matching a configured index.apps name. Omit to search all.
        top_k: Optional result count override.
    """
    return _with_runtime(retrieval.search_code, query=query, app=app, top_k=top_k)


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
