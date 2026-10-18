#!/usr/bin/env python3
"""Print a Cursor/VS Code mcp.json snippet with absolute paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def build_snippet(
    *,
    root: Path,
    name: str = "workspace-rag",
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> dict:
    root = root.resolve()
    python = root / ".venv" / "bin" / "python"
    run_mcp = root / "run_mcp.py"
    if transport == "stdio":
        entry = {
            "command": str(python),
            "args": [str(run_mcp)],
            "env": {"RAG_CONFIG": "config.yaml"},
        }
    else:
        entry = {
            "url": f"http://{host}:{int(port)}/mcp",
        }
    return {"mcpServers": {name: entry}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PACKAGE_ROOT,
        help="rag-mcp package root (default: parent of scripts/)",
    )
    parser.add_argument("--name", default="workspace-rag")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio command snippet or remote HTTP url entry",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    paths = [str(root), str(root / ".venv" / "bin" / "python"), str(root / "run_mcp.py")]
    for path in paths:
        if " " in path:
            print(
                f"warning: path contains spaces and may break some MCP clients: {path}",
                file=sys.stderr,
            )

    snippet = build_snippet(
        root=root,
        name=args.name,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )
    print(json.dumps(snippet, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
