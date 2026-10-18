"""Tests for scripts/print_mcp_json.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "print_mcp_json.py"


def _load():
    spec = importlib.util.spec_from_file_location("print_mcp_json", MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_snippet_stdio(tmp_path: Path):
    mod = _load()
    snippet = mod.build_snippet(root=tmp_path, name="ws")
    entry = snippet["mcpServers"]["ws"]
    assert entry["command"].endswith(".venv/bin/python")
    assert entry["args"][0].endswith("run_mcp.py")
    assert Path(entry["command"]).is_absolute()
    assert Path(entry["args"][0]).is_absolute()


def test_build_snippet_http(tmp_path: Path):
    mod = _load()
    snippet = mod.build_snippet(root=tmp_path, transport="http", host="127.0.0.1", port=9000)
    assert snippet["mcpServers"]["workspace-rag"]["url"] == "http://127.0.0.1:9000/mcp"


def test_main_prints_json(capsys, tmp_path: Path):
    mod = _load()
    assert mod.main(["--root", str(tmp_path), "--name", "demo"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "demo" in out["mcpServers"]
