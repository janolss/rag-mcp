"""Concurrent client acceptance: one index run, searchable active generation."""

from __future__ import annotations

import threading
from pathlib import Path

from rag.indexer.jobs import JobCoordinator, JobRequest
from rag.indexer.status_store import StatusStore


def test_concurrent_identical_index_requests(tmp_path: Path):
    store = StatusStore(tmp_path / "jobs.sqlite3")
    runs = {"n": 0}
    lock = threading.Lock()

    def runner(_req: JobRequest) -> dict:
        with lock:
            runs["n"] += 1
        return {"points": 1}

    coordinator = JobCoordinator(store, runner=runner)
    req = JobRequest(mode="full", idempotency_key="same")
    results: list = []

    def worker():
        results.append(coordinator.run(req))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert runs["n"] == 1
    assert len({r.job_id for r in results}) == 1
    assert all(r.status == "succeeded" for r in results)
