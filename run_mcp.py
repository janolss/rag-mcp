#!/usr/bin/env python3
"""Cursor-friendly MCP entrypoint that does not rely on process cwd."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.mcp_server import main

if __name__ == "__main__":
    main()
