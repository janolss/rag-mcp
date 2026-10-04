"""Httpx mock coverage for Ollama /api/embeddings request shape."""

from __future__ import annotations

import json

import httpx
import pytest

from rag.config import EmbeddingConfig
from rag.embeddings import EmbeddingClient


class _Transport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.handler(request)


def test_ollama_api_embeddings_uses_prompt(monkeypatch: pytest.MonkeyPatch):
    transport = _Transport(
        lambda req: httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
    )
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
            batch_size=8,
        )
    )
    vectors = client.embed_texts(["The sky is blue"])
    assert vectors == [[0.1, 0.2, 0.3]]
    assert len(transport.calls) == 1
    req = transport.calls[0]
    assert str(req.url) == "http://localhost:11434/api/embeddings"
    body = json.loads(req.content.decode())
    assert body == {
        "model": "nomic-embed-text:v1.5",
        "prompt": "The sky is blue",
    }


def test_ollama_api_embed_batches_input(monkeypatch: pytest.MonkeyPatch):
    transport = _Transport(
        lambda req: httpx.Response(200, json={"embeddings": [[0.1], [0.2]]})
    )
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("rag.embeddings.httpx.Client", fake_client)

    client = EmbeddingClient(
        EmbeddingConfig(
            provider="ollama",
            base_url="http://localhost:11434/api/embed",
            model="nomic-embed-text:v1.5",
            batch_size=8,
        )
    )
    vectors = client.embed_texts(["a", "b"])
    assert vectors == [[0.1], [0.2]]
    body = json.loads(transport.calls[0].content.decode())
    assert body == {"model": "nomic-embed-text:v1.5", "input": ["a", "b"]}
