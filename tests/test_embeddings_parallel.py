"""Parallel embedding preserves order."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from rag.config import EmbeddingConfig
from rag.embeddings import EmbeddingClient


class _Transport(httpx.BaseTransport):
    def __init__(self):
        self.calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        prompt = body["prompt"]
        self.calls.append(prompt)
        # Later texts finish faster → completion order differs from submit order
        time.sleep(0.02 if prompt != "a" else 0.05)
        return httpx.Response(200, json={"embedding": [float(ord(prompt[0]))]})


def test_parallel_embed_preserves_order(monkeypatch: pytest.MonkeyPatch):
    transport = _Transport()
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("rag.embeddings.httpx.Client", fake_client)

    client = EmbeddingClient(
        EmbeddingConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="nomic-embed-text:v1.5",
            concurrency=4,
            batch_size=8,
        )
    )
    vectors = client.embed_texts(["a", "b", "c", "d"])
    assert [v[0] for v in vectors] == [float(ord(ch)) for ch in "abcd"]
    assert set(transport.calls) == {"a", "b", "c", "d"}
