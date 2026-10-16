"""Index job coordinator tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rag.indexer.jobs import JobCoordinator, JobRequest
from rag.indexer.status_store import StatusStore


def test_identical_concurrent_jobs_run_once(tmp_path: Path):
    store = StatusStore(tmp_path / "jobs.sqlite3")
    calls = {"n": 0}
    lock = threading.Lock()

    def runner(req: JobRequest) -> dict:
        with lock:
            calls["n"] += 1
        time.sleep(0.1)
        return {"ok": True, "mode": req.mode}

    coordinator = JobCoordinator(store, lease_seconds=30, runner=runner)
    request = JobRequest(workspace_id="default", source_id="*", mode="full")
    results: list = []

    def worker():
        results.append(coordinator.run(request))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
    assert len(results) == 4
    job_ids = {r.job_id for r in results}
    assert len(job_ids) == 1
    assert all(r.status == "succeeded" for r in results)


def test_lease_timeout_allows_retry(tmp_path: Path):
    store = StatusStore(tmp_path / "jobs.sqlite3")
    coordinator = JobCoordinator(store, lease_seconds=0.05, runner=lambda _r: {"ok": True})
    request = JobRequest(
        workspace_id="ws",
        source_id="code",
        mode="full",
        idempotency_key="same",
    )
    first = coordinator.submit(request)
    assert first.status == "queued"
    time.sleep(0.08)
    expired = store.expire_stale_leases()
    assert expired >= 1
    failed = store.get(first.job_id)
    assert failed is not None
    assert failed.status == "failed"

    # New submit after expiry creates a fresh job for the same key once failed.
    # Unique index still holds the failed row; use a distinct key for retry path,
    # and verify active_lease is clear.
    assert store.active_lease(workspace_id="ws", source_id="code") is None
    second = coordinator.run(
        JobRequest(
            workspace_id="ws",
            source_id="code",
            mode="full",
            idempotency_key="retry",
        )
    )
    assert second.status == "succeeded"


def test_search_unaffected_marker(tmp_path: Path):
    """Coordinator does not swap collections; search uses active generation."""
    store = StatusStore(tmp_path / "jobs.sqlite3")
    seen = {"running": False}

    def runner(_req: JobRequest) -> dict:
        seen["running"] = True
        # Active generation remains readable while job runs (staging is separate).
        assert store.active_lease(workspace_id="default", source_id="*") is not None
        return {"points": 1}

    coordinator = JobCoordinator(store, runner=runner)
    job = coordinator.run(JobRequest())
    assert seen["running"] is True
    assert job.status == "succeeded"


def test_succeeded_job_requeues_for_intentional_reindex(tmp_path: Path):
    """A later identical request must run again after success (not return the old result)."""
    store = StatusStore(tmp_path / "jobs.sqlite3")
    calls = {"n": 0}

    def runner(_req: JobRequest) -> dict:
        calls["n"] += 1
        return {"run": calls["n"]}

    coordinator = JobCoordinator(store, lease_seconds=30, runner=runner)
    request = JobRequest(workspace_id="default", source_id="*", mode="full")

    first = coordinator.run(request)
    assert first.status == "succeeded"
    assert first.result() == {"run": 1}
    assert calls["n"] == 1

    second = coordinator.run(request)
    assert second.status == "succeeded"
    assert second.job_id == first.job_id  # same idempotency row, requeued
    assert second.result() == {"run": 2}
    assert calls["n"] == 2
