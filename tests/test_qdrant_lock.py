"""Tests for Qdrant local lock retries."""

from __future__ import annotations

import pytest

from rag.config import Config, QdrantConfig
from rag.store import QdrantLockError, VectorStore, lock_error_message


def test_lock_error_message_mentions_server_mode():
    msg = lock_error_message("/tmp/qdrant_data")
    assert "qdrant.mode=server" in msg
    assert "/tmp/qdrant_data" in msg


def test_connect_retries_then_raises(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    class Boom:
        def __init__(self, *args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("Storage folder ... is already accessed by another instance")

    monkeypatch.setattr("rag.store.QdrantClient", Boom)
    monkeypatch.setattr("rag.store.time.sleep", lambda _s: None)

    cfg = Config(qdrant=QdrantConfig(mode="local", connect_retries=3, connect_retry_delay_ms=1))
    with pytest.raises(QdrantLockError, match="locked"):
        VectorStore(cfg)
    assert calls["n"] == 3


def test_connect_succeeds_after_transient_lock(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    state = {"n": 0}

    def factory(*args, **kwargs):
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("Storage folder is already accessed by another instance")
        return FakeClient()

    monkeypatch.setattr("rag.store.QdrantClient", factory)
    monkeypatch.setattr("rag.store.time.sleep", lambda _s: None)

    cfg = Config(qdrant=QdrantConfig(mode="local", connect_retries=5, connect_retry_delay_ms=1))
    store = VectorStore(cfg)
    assert state["n"] == 3
    store.close()
