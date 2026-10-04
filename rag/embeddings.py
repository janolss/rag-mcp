"""Embeddings HTTP client: OpenAI-compatible and Ollama native APIs."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Sequence

import httpx

from rag.config import EmbeddingConfig

logger = logging.getLogger(__name__)

VALID_PROVIDERS = frozenset({"openai", "ollama"})


def normalize_embeddings_url(base_url: str, provider: str = "openai") -> str:
    """
    Resolve the embeddings endpoint from a base URL + provider.

    openai  → {base}/v1/embeddings
    ollama  → {base}/api/embeddings  (native; also accepts full /api/embed URL)
    """
    base = base_url.strip().rstrip("/")
    provider = (provider or "openai").strip().lower()

    if provider == "ollama":
        if base.endswith("/api/embeddings") or base.endswith("/api/embed"):
            return base
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/api/embeddings"

    if provider != "openai":
        raise ValueError(f"Unsupported embedding.provider: {provider!r} (use openai|ollama)")

    if base.endswith("/embeddings"):
        return base
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


class EmbeddingClient:
    """HTTP embeddings client for OpenAI-compatible servers and Ollama."""

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._provider = (config.provider or "openai").strip().lower()
        if self._provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding.provider: {config.provider!r} (use openai|ollama)"
            )
        self._url = normalize_embeddings_url(config.base_url, self._provider)
        self._timeout = config.timeout_ms / 1000.0
        self._max_input_chars = max(0, int(getattr(config, "max_input_chars", 0) or 0))
        self._concurrency = max(1, int(getattr(config, "concurrency", 1) or 1))

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def url(self) -> str:
        return self._url

    @property
    def provider(self) -> str:
        return self._provider

    def embed_texts(self, texts: Sequence[str], *, for_query: bool = False) -> list[list[float]]:
        if not texts:
            return []

        prefix = self._config.query_prefix if for_query else self._config.document_prefix
        prepared = [f"{prefix}{text}" if prefix else text for text in texts]
        prepared = [self._clamp_input(text) for text in prepared]

        batch_size = max(1, self._config.batch_size)
        # Native /api/embeddings only accepts a single prompt per request
        if self._provider == "ollama" and self._url.endswith("/api/embeddings"):
            batch_size = 1

        batches: list[tuple[int, list[str]]] = []
        for start in range(0, len(prepared), batch_size):
            batches.append((start, prepared[start : start + batch_size]))

        if self._concurrency == 1 or len(batches) == 1:
            return self._embed_batches_serial(batches, total=len(prepared))
        return self._embed_batches_parallel(batches, total=len(prepared))

    def embed_query(self, query: str) -> list[float]:
        results = self.embed_texts([query], for_query=True)
        return results[0]

    def health_check(self) -> tuple[bool, str]:
        try:
            vector = self.embed_query("health check")
            if not vector:
                return False, "Embedding endpoint returned an empty vector"
            return (
                True,
                f"ok dim={len(vector)} model={self.model} "
                f"provider={self.provider} concurrency={self._concurrency}",
            )
        except Exception as exc:  # noqa: BLE001 - surface any transport/API failure
            return False, str(exc)

    def _clamp_input(self, text: str) -> str:
        if self._max_input_chars <= 0 or len(text) <= self._max_input_chars:
            return text
        logger.warning(
            "Truncating embedding input from %d to %d chars (max_input_chars)",
            len(text),
            self._max_input_chars,
        )
        return text[: self._max_input_chars]

    def _embed_batches_serial(
        self,
        batches: list[tuple[int, list[str]]],
        *,
        total: int,
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self._timeout) as client:
            for start, batch in batches:
                logger.info(
                    "Embedding %d–%d / %d (concurrency=1)",
                    start + 1,
                    start + len(batch),
                    total,
                )
                vectors.extend(self._embed_batch(client, batch))
        return vectors

    def _embed_batches_parallel(
        self,
        batches: list[tuple[int, list[str]]],
        *,
        total: int,
    ) -> list[list[float]]:
        """Run embedding batches concurrently; preserve input order in the result."""
        results: dict[int, list[list[float]]] = {}
        done = 0
        lock = threading.Lock()
        workers = min(self._concurrency, len(batches))
        logger.info(
            "Embedding %d texts in %d batches with concurrency=%d",
            total,
            len(batches),
            workers,
        )

        def worker(start: int, batch: list[str]) -> tuple[int, list[list[float]]]:
            with httpx.Client(timeout=self._timeout) as client:
                return start, self._embed_batch(client, batch)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker, start, batch) for start, batch in batches]
            for future in as_completed(futures):
                start, vectors = future.result()
                results[start] = vectors
                with lock:
                    done += len(vectors)
                    logger.info("Embedded %d / %d", done, total)

        ordered: list[list[float]] = []
        for start, _batch in batches:
            ordered.extend(results[start])
        return ordered

    def _embed_batch(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        if self._provider == "ollama":
            return self._embed_ollama(client, texts)
        return self._embed_openai(client, texts)

    def _embed_openai(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self._config.model,
            "input": texts if len(texts) > 1 else texts[0],
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        body = self._post(client, payload, headers)
        return self._parse_openai_response(body)

    def _embed_ollama(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        # /api/embed supports batched "input"; /api/embeddings uses single "prompt"
        if self._url.endswith("/api/embed"):
            payload = {
                "model": self._config.model,
                "input": texts if len(texts) > 1 else texts[0],
            }
            body = self._post(client, payload)
            return self._parse_ollama_embed_response(body, expected=len(texts))

        if len(texts) != 1:
            raise RuntimeError("Ollama /api/embeddings accepts one prompt per request")
        payload = {
            "model": self._config.model,
            "prompt": texts[0],
        }
        body = self._post(client, payload)
        embedding = body.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError(f"Unexpected Ollama /api/embeddings response from {self._url}")
        return [embedding]

    def _post(
        self,
        client: httpx.Client,
        payload: dict,
        headers: dict[str, str] | None = None,
    ) -> dict:
        response = client.post(self._url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Embeddings request failed ({response.status_code}) at {self._url}: "
                f"{response.text[:500]}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected embeddings response type from {self._url}")
        return body

    def _parse_openai_response(self, body: dict) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list) or not data:
            if "embedding" in body and isinstance(body["embedding"], list):
                return [body["embedding"]]
            raise RuntimeError(f"Unexpected embeddings response shape from {self._url}")

        indexed = []
        for item in data:
            if "embedding" not in item:
                raise RuntimeError("Embeddings response item missing 'embedding'")
            indexed.append((item.get("index", len(indexed)), item["embedding"]))
        indexed.sort(key=lambda pair: pair[0])
        return [embedding for _, embedding in indexed]

    def _parse_ollama_embed_response(self, body: dict, *, expected: int) -> list[list[float]]:
        embeddings = body.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            if len(embeddings) != expected:
                raise RuntimeError(
                    f"Ollama returned {len(embeddings)} embeddings, expected {expected}"
                )
            return embeddings
        # Some builds return a single embedding for one input
        embedding = body.get("embedding")
        if isinstance(embedding, list) and embedding and expected == 1:
            return [embedding]
        raise RuntimeError(f"Unexpected Ollama /api/embed response from {self._url}")
