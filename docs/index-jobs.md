# Index jobs

Long-running index work goes through `JobCoordinator` so concurrent identical
requests share one execution while search keeps reading the active generation.

## Model

| Field | Meaning |
|-------|---------|
| `job_id` | UUID |
| `workspace_id` / `source_id` | Lease scope (`source_id='*'` for full workspace) |
| `idempotency_key` | Deduplicate identical requests |
| `status` | `queued` → `running` → `succeeded` / `failed` |
| `lease_expires_at` | Stale runners are marked failed and can be retried |

SQLite file: next to `index_status.json` as `index_jobs.sqlite3`.

## CLI

`python -m rag.cli index` and `index --files …` call `run_index_job(..., wait=True)`
so the process blocks until the coordinated job finishes.

## Guarantees

- Two identical concurrent jobs produce **one** index run.
- Staging rebuilds still activate only after verification; search stays
  on the previous active collection during the job.
- Lease expiry unlocks the scope for a retry.

## Recovery

Expired leases become `failed` with error `lease expired`. Submitting the same
idempotency key requeues that row.
