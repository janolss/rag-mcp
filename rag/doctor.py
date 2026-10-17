"""Local environment and config health checks."""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from rag.config import PACKAGE_ROOT, Config
from rag.embeddings import EmbeddingClient
from rag.indexer.git_info import git_head_sha
from rag.indexer.run import status_report
from rag.store import QdrantLockError, VectorStore

CheckStatus = Literal["ok", "warn", "fail"]

_VENV_HINT = (
    "Recreate the virtualenv from the package root:\n"
    "  rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate\n"
    '  pip install -e ".[dev,parsers]"'
)


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str


def _expected_venv_prefix() -> Path:
    return (PACKAGE_ROOT / ".venv").resolve()


def check_python() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        return CheckResult("python", "fail", f"Python {major}.{minor} < 3.10")
    prefix = Path(sys.prefix).resolve()
    expected = _expected_venv_prefix()
    exe = Path(sys.executable).resolve()
    msg = f"{major}.{minor}.{sys.version_info[2]} executable={exe}"
    foreign_venv = (
        expected.exists()
        and expected not in prefix.parents
        and prefix != expected
        and ".venv" in str(exe)
        and not str(exe).startswith(str(PACKAGE_ROOT))
    )
    if foreign_venv:
        return CheckResult(
            "python",
            "warn",
            f"{msg}. Venv looks relocated or foreign. {_VENV_HINT}",
        )
    return CheckResult("python", "ok", msg)


def check_imports() -> CheckResult:
    missing: list[str] = []
    for name in ("mcp", "qdrant_client", "httpx", "yaml", "pydantic", "starlette", "uvicorn"):
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        return CheckResult(
            "imports",
            "fail",
            f'missing modules: {", ".join(missing)}. pip install -e ".[parsers]"',
        )
    return CheckResult("imports", "ok", "core packages importable")


def check_config(config: Config) -> CheckResult:
    return CheckResult(
        "config",
        "ok",
        f"collection={config.qdrant.collection} mode={config.qdrant.mode} "
        f"transport={config.mcp.transport}",
    )


def check_qdrant(config: Config) -> CheckResult:
    mode = config.qdrant.mode
    if mode == "memory":
        return CheckResult("qdrant", "ok", "mode=memory")
    if mode == "server":
        key = "set" if (config.qdrant.api_key or "").strip() else "unset"
        return CheckResult(
            "qdrant",
            "ok",
            f"mode=server url={config.qdrant.url} api_key={key}",
        )
    if mode != "local":
        return CheckResult("qdrant", "fail", f"unsupported mode {mode!r}")
    try:
        store = VectorStore(config, connect_retries=1, connect_retry_delay_ms=0)
        exists = store.collection_exists()
        store.close()
    except QdrantLockError as exc:
        return CheckResult("qdrant", "fail", str(exc))
    except Exception as exc:
        return CheckResult("qdrant", "fail", f"local open failed: {exc}")
    if not exists:
        return CheckResult(
            "qdrant",
            "warn",
            f"local path open ok; collection {config.qdrant.collection!r} missing "
            "(run: python -m rag.cli index)",
        )
    return CheckResult("qdrant", "ok", f"local collection {config.qdrant.collection!r} present")


def check_embedding(config: Config, *, skip_network: bool) -> CheckResult:
    if skip_network:
        return CheckResult(
            "embedding",
            "ok",
            f"skipped (provider={config.embedding.provider} model={config.embedding.model})",
        )
    ok, detail = EmbeddingClient(config.embedding).health_check()
    return CheckResult("embedding", "ok" if ok else "fail", detail)


def check_index_freshness(config: Config) -> CheckResult:
    try:
        report = status_report(config)
    except QdrantLockError as exc:
        return CheckResult("index", "warn", str(exc))
    except Exception as exc:
        return CheckResult("index", "warn", f"status unavailable: {exc}")

    points = int(report.get("points_count") or 0)
    indexed_model = report.get("embedding_model") or report.get("model")
    current_model = config.embedding.model
    head = git_head_sha(config.repo_root_path)
    git_sha = report.get("git_sha") or ""
    notes: list[str] = [f"points={points}"]
    status: CheckStatus = "ok"
    if points == 0:
        status = "warn"
        notes.append("empty index")
    if indexed_model and indexed_model != current_model:
        status = "warn"
        notes.append(f"model mismatch index={indexed_model!r} config={current_model!r}")
    if git_sha and head and git_sha != head:
        status = "warn"
        notes.append(f"git_sha index={git_sha[:8]} head={head[:8]}")
    return CheckResult("index", status, "; ".join(notes))


def run_doctor(config: Config, *, skip_network: bool = False) -> list[CheckResult]:
    results = [
        check_python(),
        check_imports(),
        check_config(config),
        check_qdrant(config),
        check_embedding(config, skip_network=skip_network),
        check_index_freshness(config),
    ]
    return results


def doctor_exit_code(results: list[CheckResult]) -> int:
    if any(r.status == "fail" for r in results):
        return 1
    return 0


def format_doctor_report(results: list[CheckResult], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps([asdict(r) for r in results], indent=2) + "\n"
    lines = []
    for r in results:
        lines.append(f"[{r.status.upper():4}] {r.name}: {r.message}")
    return "\n".join(lines) + "\n"
