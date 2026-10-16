"""Restart/resume acceptance for incremental registry and jobs."""

from __future__ import annotations

from pathlib import Path

from rag.indexer.document_registry import DocumentRecord, DocumentRegistry
from rag.indexer.jobs import JobCoordinator, JobRequest
from rag.indexer.status_store import StatusStore


def test_registry_survives_reopen(tmp_path: Path):
    path = tmp_path / "reg.sqlite3"
    registry = DocumentRegistry(path)
    registry.upsert(
        DocumentRecord(
            workspace_id="default",
            source_id="knowledge",
            document_id="a.md",
            content_hash="abc",
            revision=2,
            status="writing",
            observed_at=1.0,
            path="a.md",
        )
    )
    reopened = DocumentRegistry(path)
    loaded = reopened.get("default", "knowledge", "a.md")
    assert loaded is not None
    assert loaded.status == "writing"
    assert loaded.revision == 2
    # Resume path: mark active after successful rewrite.
    reopened.upsert(
        DocumentRecord(
            workspace_id="default",
            source_id="knowledge",
            document_id="a.md",
            content_hash="abc",
            revision=2,
            status="active",
            observed_at=2.0,
            path="a.md",
        )
    )
    assert reopened.get("default", "knowledge", "a.md").status == "active"


def test_job_coordinator_resume_after_failure(tmp_path: Path):
    store = StatusStore(tmp_path / "jobs.sqlite3")
    calls = {"n": 0}

    def runner(_req: JobRequest) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    coordinator = JobCoordinator(store, runner=runner, lease_seconds=30)
    req = JobRequest(idempotency_key="k1")
    try:
        coordinator.run(req)
    except RuntimeError:
        pass
    failed = store.get_by_idempotency(workspace_id="default", source_id="*", idempotency_key="k1")
    assert failed is not None
    assert failed.status == "failed"
    succeeded = coordinator.run(req)
    assert succeeded.status == "succeeded"
    assert calls["n"] == 2
