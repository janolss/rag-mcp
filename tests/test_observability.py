"""Observability: correlation IDs, redaction, health/ready/metrics."""

from __future__ import annotations

from pathlib import Path

from rag.config import Config, EmbeddingConfig, IndexConfig, QdrantConfig, SearchConfig
from rag.http_api import CORRELATION_HEADER, create_api_app
from rag.observability import (
    METRICS,
    correlation_scope,
    derive_lifecycle,
    get_correlation_id,
    redact,
)
from starlette.testclient import TestClient


def _config(tmp_path: Path) -> Config:
    return Config(
        embedding=EmbeddingConfig(model="fake"),
        qdrant=QdrantConfig(mode="memory", collection="obs"),
        index=IndexConfig(
            repo_root=str(tmp_path),
            status_file=str(tmp_path / "status.json"),
            knowledge=[],
            code=[],
            sources="knowledge",
        ),
        search=SearchConfig(score_threshold=0.0),
    )


def test_redact_secrets():
    assert "[REDACTED]" in redact("api_key=super-secret-value")
    assert "BEGIN" not in redact("-----BEGIN PRIVATE KEY-----\nabc\n")


def test_correlation_scope_and_lifecycle():
    with correlation_scope("abc123"):
        assert get_correlation_id() == "abc123"
    assert derive_lifecycle(None, points_count=0) == "not_indexed"
    assert derive_lifecycle({"index_mode": "partial"}, points_count=3) == "partial"
    assert derive_lifecycle({"updated_at": "x"}, points_count=2) == "ready"
    assert derive_lifecycle({"error": "boom"}, points_count=0) == "error"


def test_health_ready_metrics_and_correlation_header(tmp_path: Path):
    client = TestClient(create_api_app(_config(tmp_path)))
    health = client.get("/health", headers={CORRELATION_HEADER: "corr-1"})
    assert health.status_code == 200
    assert health.headers.get(CORRELATION_HEADER) == "corr-1"

    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["ready"] is False

    status = client.get("/api/v1/index/status")
    assert status.status_code == 200
    assert status.json()["lifecycle"] == "not_indexed"
    assert "correlation_id" in status.json()

    METRICS.incr("rag_test_total")
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "rag_test_total" in metrics.text or "rag_index_status_total" in metrics.text
