"""Index job coordinator: lease, idempotency, and synchronous wait."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.indexer.status_store import JobRecord, StatusStore

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300.0
_GLOBAL_LOCK = threading.RLock()


@dataclass(frozen=True)
class JobRequest:
    workspace_id: str = "default"
    source_id: str = "*"
    mode: str = "full"
    files: tuple[str, ...] = ()
    idempotency_key: str | None = None


class JobCoordinator:
    """
    Coordinate index jobs so identical concurrent requests share one run.

    Search continues against the active collection generation; staging rebuilds
    do not swap the active pointer until success (see CollectionRouter).
    """

    def __init__(
        self,
        store: StatusStore,
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        runner: Callable[[JobRequest], dict[str, Any]] | None = None,
    ):
        self.store = store
        self.lease_seconds = lease_seconds
        self._runner = runner
        self._local = threading.RLock()

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        runner: Callable[[JobRequest], dict[str, Any]] | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> JobCoordinator:
        path = jobs_db_path(config)
        return cls(StatusStore(path), lease_seconds=lease_seconds, runner=runner)

    def submit(self, request: JobRequest) -> JobRecord:
        """
        Enqueue or join an existing *active* job with the same idempotency key.

        Only ``queued`` / ``running`` jobs are shared (concurrent dedupe). A prior
        ``succeeded`` / ``failed`` / ``cancelled`` row is requeued so intentional
        reindex runs again under the same key.
        """
        key = request.idempotency_key or default_idempotency_key(request)
        normalized = JobRequest(
            workspace_id=request.workspace_id,
            source_id=request.source_id,
            mode=request.mode,
            files=tuple(request.files),
            idempotency_key=key,
        )
        with _GLOBAL_LOCK, self._local:
            self.store.expire_stale_leases()
            existing = self.store.get_by_idempotency(
                workspace_id=normalized.workspace_id,
                source_id=normalized.source_id,
                idempotency_key=key,
            )
            if existing is not None:
                if existing.status in {"queued", "running"} and (
                    existing.lease_expires_at is None or existing.lease_expires_at > time.time()
                ):
                    return existing
                # Terminal or expired: requeue under the same idempotency key.
                if existing.status in {"succeeded", "failed", "cancelled"} or (
                    existing.lease_expires_at is not None
                    and existing.lease_expires_at <= time.time()
                ):
                    requeued = self.store.update(
                        existing.job_id,
                        status="queued",
                        lease_expires_at=time.time() + self.lease_seconds,
                        error="",
                        clear_result=True,
                    )
                    assert requeued is not None
                    return requeued

            now = time.time()
            record = JobRecord(
                job_id=str(uuid.uuid4()),
                workspace_id=normalized.workspace_id,
                source_id=normalized.source_id,
                mode=normalized.mode,
                idempotency_key=key,
                status="queued",
                created_at=now,
                updated_at=now,
                lease_expires_at=now + self.lease_seconds,
            )
            try:
                return self.store.insert(record)
            except Exception:
                # Unique idempotency race: join an in-flight winner, or requeue
                # a terminal row the same way as the lookup path above.
                winner = self.store.get_by_idempotency(
                    workspace_id=normalized.workspace_id,
                    source_id=normalized.source_id,
                    idempotency_key=key,
                )
                if winner is None:
                    raise
                if winner.status in {"queued", "running"} and (
                    winner.lease_expires_at is None or winner.lease_expires_at > time.time()
                ):
                    return winner
                if winner.status in {"succeeded", "failed", "cancelled"} or (
                    winner.lease_expires_at is not None and winner.lease_expires_at <= time.time()
                ):
                    requeued = self.store.update(
                        winner.job_id,
                        status="queued",
                        lease_expires_at=time.time() + self.lease_seconds,
                        error="",
                        clear_result=True,
                    )
                    assert requeued is not None
                    return requeued
                raise

    def run(self, request: JobRequest) -> JobRecord:
        """Submit and execute synchronously (CLI wait mode)."""
        job = self.submit(request)
        if job.status == "running":
            return self.wait(job.job_id)

        claimed = self._claim(job.job_id)
        if claimed is None:
            current = self.store.get(job.job_id)
            if current and current.status == "succeeded":
                return current
            return self.wait(job.job_id)

        runner = self._runner or _default_runner_for_config
        try:
            # Bind config via closure attribute if provided by factory.
            result = runner(request)
            updated = self.store.update(
                claimed.job_id,
                status="succeeded",
                clear_lease=True,
                result=result,
                error="",
            )
            assert updated is not None
            return updated
        except Exception as exc:
            logger.exception("Index job %s failed", claimed.job_id)
            updated = self.store.update(
                claimed.job_id,
                status="failed",
                clear_lease=True,
                error=str(exc),
            )
            assert updated is not None
            raise

    def wait(self, job_id: str, *, timeout: float = 600.0, poll: float = 0.05) -> JobRecord:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.store.expire_stale_leases()
            job = self.store.get(job_id)
            if job is None:
                raise RuntimeError(f"unknown job: {job_id}")
            if job.status in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(poll)
        raise TimeoutError(f"timed out waiting for job {job_id}")

    def _claim(self, job_id: str) -> JobRecord | None:
        with _GLOBAL_LOCK, self._local:
            job = self.store.get(job_id)
            if job is None or job.status != "queued":
                return None
            active = self.store.active_lease(
                workspace_id=job.workspace_id,
                source_id=job.source_id,
            )
            if active and active.job_id != job.job_id and active.status == "running":
                return None
            return self.store.update(
                job_id,
                status="running",
                lease_expires_at=time.time() + self.lease_seconds,
            )


def jobs_db_path(config: Config) -> Path:
    return config.status_file_path.parent / "index_jobs.sqlite3"


def default_idempotency_key(request: JobRequest) -> str:
    raw = "|".join(
        [
            request.workspace_id,
            request.source_id,
            request.mode,
            ",".join(sorted(request.files)),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_index_job(
    config: Config,
    *,
    files: Sequence[str] | None = None,
    workspace_id: str | None = None,
    wait: bool = True,
) -> dict[str, Any]:
    """CLI/server entry: coordinate then optionally wait for completion."""
    from rag.workspaces import WorkspaceRegistry

    registry = WorkspaceRegistry.from_config(config)
    resolved_workspace = workspace_id
    if resolved_workspace is None:
        ids = registry.ids()
        resolved_workspace = ids[0] if len(ids) == 1 else "*"
    elif resolved_workspace != "*":
        registry.get(resolved_workspace)

    if files and resolved_workspace == "*":
        raise RuntimeError(
            "workspace_id is required for partial index when multiple workspaces "
            "are registered (pass --workspace-id)"
        )

    request = JobRequest(
        workspace_id=resolved_workspace,
        source_id="*",
        mode="partial" if files else "full",
        files=tuple(files or ()),
    )

    def runner(req: JobRequest) -> dict[str, Any]:
        from rag.indexer.run import run_index, run_index_files

        scoped = None if req.workspace_id == "*" else req.workspace_id
        if req.files:
            return run_index_files(config, list(req.files), workspace_id=scoped)
        return run_index(config, workspace_id=scoped)

    coordinator = JobCoordinator.from_config(config, runner=runner)
    if not wait:
        job = coordinator.submit(request)
        return {"job": job.to_dict()}
    job = coordinator.run(request)
    payload = job.to_dict()
    if job.result():
        payload.update(job.result() or {})
    payload["job_id"] = job.job_id
    payload["job_status"] = job.status
    return payload


def _default_runner_for_config(request: JobRequest) -> dict[str, Any]:
    raise RuntimeError("JobCoordinator runner was not configured")
