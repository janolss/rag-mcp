"""Tests for rag.cli doctor checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig
from rag.doctor import (
    check_embedding,
    check_imports,
    check_python,
    doctor_exit_code,
    format_doctor_report,
    run_doctor,
)


def test_check_python_and_imports_ok():
    assert check_python().status in {"ok", "warn"}
    assert check_imports().status == "ok"


def test_run_doctor_skip_network(tmp_path: Path):
    from tests.workspace_fixtures import with_workspace_manifest

    config = with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="doctor"),
            index=IndexConfig(
                repo_root=str(tmp_path),
                status_file=str(tmp_path / "status.json"),
                knowledge=[],
                code=[],
            ),
        ),
        tmp_path,
    )
    results = run_doctor(config, skip_network=True)
    names = {r.name for r in results}
    assert {
        "python",
        "imports",
        "config",
        "manifests",
        "qdrant",
        "embedding",
        "index_manifest",
        "index",
        "sources",
    } <= names
    assert next(r for r in results if r.name == "manifests").status == "ok"
    emb = next(r for r in results if r.name == "embedding")
    assert emb.status == "ok"
    assert "skipped" in emb.message
    assert doctor_exit_code(results) in {0, 1}
    text = format_doctor_report(results)
    assert "[OK" in text or "[WARN" in text or "[FAIL" in text


def test_check_embedding_skip(tmp_path: Path):
    config = Config(embedding=EmbeddingConfig(provider="openai", model="x"))
    result = check_embedding(config, skip_network=True)
    assert result.status == "ok"
    assert "skipped" in result.message


def test_empty_index_warns_with_index_command(tmp_path: Path):
    from rag.doctor import check_index_freshness
    from tests.workspace_fixtures import with_workspace_manifest

    config = with_workspace_manifest(
        Config(
            embedding=EmbeddingConfig(model="fake"),
            qdrant=QdrantConfig(mode="memory", collection="doctor_empty"),
            index=IndexConfig(
                repo_root=str(tmp_path),
                status_file=str(tmp_path / "status.json"),
                knowledge=[],
                code=[],
            ),
        ),
        tmp_path,
    )
    result = check_index_freshness(config)
    assert result.status == "warn"
    assert "empty index" in result.message
    assert "rag.cli index" in result.message


def test_cli_doctor_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from rag import cli
    from tests.workspace_fixtures import write_workspace_manifest

    manifest = write_workspace_manifest(tmp_path / "ws.yaml", root=tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"workspace_manifests:\n  - {manifest}\n"
        "qdrant:\n  mode: memory\n  collection: doctor_cli\nembedding:\n  model: fake\n"
        f"index:\n  repo_root: {tmp_path}\n  status_file: {tmp_path / 'status.json'}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    code = cli.main(["--config", str(config_path), "doctor", "--skip-network"])
    assert code in {0, 1}
