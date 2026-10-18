"""Embedding client circuit breaker tests."""

from __future__ import annotations

import pytest
from rag.config import EmbeddingConfig
from rag.embeddings import EmbeddingClient


def test_circuit_opens_after_consecutive_failures(monkeypatch: pytest.MonkeyPatch):
    cfg = EmbeddingConfig(
        provider="openai",
        base_url="http://example.invalid/v1",
        model="m",
        timeout_ms=100,
        circuit_breaker_failures=2,
        circuit_breaker_seconds=60,
    )
    client = EmbeddingClient(cfg)

    def boom(*_a, **_k):
        raise RuntimeError("embeddings down")

    monkeypatch.setattr(client, "_embed_batch", boom)

    with pytest.raises(RuntimeError, match="embeddings down"):
        client.embed_texts(["a"])
    with pytest.raises(RuntimeError, match="embeddings down"):
        client.embed_texts(["b"])
    with pytest.raises(RuntimeError, match="circuit open"):
        client.embed_texts(["c"])


def test_circuit_disabled_when_threshold_zero(monkeypatch: pytest.MonkeyPatch):
    cfg = EmbeddingConfig(
        provider="openai",
        base_url="http://example.invalid/v1",
        model="m",
        circuit_breaker_failures=0,
        circuit_breaker_seconds=60,
    )
    client = EmbeddingClient(cfg)
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("embeddings down")

    monkeypatch.setattr(client, "_embed_batch", boom)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="embeddings down"):
            client.embed_texts(["x"])
    assert calls["n"] == 3


def test_circuit_recovers_after_success(monkeypatch: pytest.MonkeyPatch):
    cfg = EmbeddingConfig(
        provider="openai",
        base_url="http://example.invalid/v1",
        model="m",
        circuit_breaker_failures=2,
        circuit_breaker_seconds=0.01,
    )
    client = EmbeddingClient(cfg)
    state = {"fail": True}

    def flaky(_c, texts):
        if state["fail"]:
            raise RuntimeError("embeddings down")
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(client, "_embed_batch", flaky)
    with pytest.raises(RuntimeError):
        client.embed_texts(["a"])
    with pytest.raises(RuntimeError):
        client.embed_texts(["b"])
    # Force half-open by clearing open window.
    client._breaker._opened_at = 0.0
    state["fail"] = False
    vectors = client.embed_texts(["ok"])
    assert vectors == [[0.1, 0.2]]
