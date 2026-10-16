"""Correlation IDs, structured logs, latency metrics (no sensitive content)."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

IndexLifecycle = Literal["not_indexed", "indexing", "ready", "partial", "error"]

_correlation_id: ContextVar[str | None] = ContextVar("rag_correlation_id", default=None)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

logger = logging.getLogger(__name__)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


@contextmanager
def correlation_scope(correlation_id: str | None = None) -> Iterator[str]:
    token = _correlation_id.set(correlation_id or new_correlation_id())
    try:
        yield _correlation_id.get() or ""
    finally:
        _correlation_id.reset(token)


def redact(text: str) -> str:
    """Strip credential-like material from log strings."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


@dataclass
class MetricsRegistry:
    """In-process counters and latency aggregates (Prometheus text export)."""

    counters: dict[str, float] = field(default_factory=dict)
    latency_sum: dict[str, float] = field(default_factory=dict)
    latency_count: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def incr(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self.counters[key] = self.counters.get(key, 0.0) + value

    def observe_latency(self, name: str, seconds: float, **labels: str) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self.latency_sum[key] = self.latency_sum.get(key, 0.0) + seconds
            self.latency_count[key] = self.latency_count.get(key, 0.0) + 1.0

    @contextmanager
    def timer(self, name: str, **labels: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe_latency(name, time.perf_counter() - start, **labels)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in sorted(self.counters.items()):
                lines.append(f"{key} {value}")
            for key, total in sorted(self.latency_sum.items()):
                count = self.latency_count.get(key, 0.0)
                lines.append(f"{key}_sum {total}")
                lines.append(f"{key}_count {count}")
        return "\n".join(lines) + ("\n" if lines else "")


METRICS = MetricsRegistry()


def structured_log(
    level: int,
    message: str,
    *,
    workspace_id: str | None = None,
    source_id: str | None = None,
    job_id: str | None = None,
    **extra: Any,
) -> None:
    payload = {
        "msg": redact(message),
        "correlation_id": get_correlation_id(),
        "workspace_id": workspace_id,
        "source_id": source_id,
        "job_id": job_id,
        **{k: redact(str(v)) if isinstance(v, str) else v for k, v in extra.items()},
    }
    logger.log(level, "%s", payload)


def derive_lifecycle(status: dict[str, Any] | None, *, points_count: int) -> IndexLifecycle:
    if status is None:
        return "not_indexed"
    if status.get("error"):
        return "error"
    if status.get("index_mode") == "partial":
        return "partial"
    if points_count > 0:
        return "ready"
    return "not_indexed"


def _metric_key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"
