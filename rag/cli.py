"""CLI entrypoints: index, status, search."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from rag.config import PACKAGE_ROOT, load_config
from rag.indexer.run import run_index, run_index_files, status_report
from rag.retrieval.search import search_code, search_knowledge, search_lis
from rag.store import QdrantLockError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workspace RAG toolkit")
    parser.add_argument(
        "--config",
        default=os.environ.get("RAG_CONFIG", "config.yaml"),
        help="Path to config.yaml (relative to package root unless absolute)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index", help="Full rebuild of the Qdrant collection")
    index_parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Partial upsert for repo-relative or absolute paths (does not recreate collection)",
    )
    sub.add_parser("status", help="Show index/collection status")

    search = sub.add_parser("search", help="Debug search against the index")
    search.add_argument("query", help="Search query")
    search.add_argument(
        "--mode",
        choices=["knowledge", "code", "lis"],
        default="knowledge",
        help="Which tool surface to emulate",
    )
    search.add_argument(
        "--app",
        default=None,
        help="Optional app filter (must match a configured index.apps name)",
    )
    search.add_argument(
        "--path-prefix",
        default=None,
        help="Optional repo-relative path prefix filter",
    )
    search.add_argument("--doc-type", default=None, help="LIS doc_type filter")
    search.add_argument("--process-area", default=None, help="LIS process_area filter")
    search.add_argument("--domain", default=None, help="LIS domain filter")
    search.add_argument("--status", default=None, help="LIS status filter")
    search.add_argument("--top-k", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PACKAGE_ROOT / ".env")
    os.chdir(PACKAGE_ROOT)

    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "index":
        try:
            if args.files:
                status = run_index_files(config, args.files)
            else:
                status = run_index(config)
        except QdrantLockError as exc:
            logging.error("%s", exc)
            print(str(exc), file=sys.stderr)
            return 1
        except RuntimeError as exc:
            logging.error("%s", exc)
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(status, indent=2))
        return 0

    if args.command == "status":
        try:
            report = status_report(config)
        except QdrantLockError as exc:
            logging.error("%s", exc)
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "search":
        try:
            if args.mode == "knowledge":
                print(
                    search_knowledge(
                        config,
                        args.query,
                        top_k=args.top_k,
                        path_prefix=args.path_prefix,
                    )
                )
            elif args.mode == "lis":
                print(
                    search_lis(
                        config,
                        args.query,
                        top_k=args.top_k,
                        path_prefix=args.path_prefix,
                        doc_type=args.doc_type,
                        process_area=args.process_area,
                        domain=args.domain,
                        status=args.status,
                    )
                )
            else:
                print(
                    search_code(
                        config,
                        args.query,
                        app=args.app,
                        top_k=args.top_k,
                        path_prefix=args.path_prefix,
                    )
                )
        except QdrantLockError as exc:
            logging.error("%s", exc)
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
