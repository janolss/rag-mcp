# Incremental indexing

Partial updates use a SQLite document registry plus hash inventory so reruns are
idempotent and failed writes do not retire the previous generation of chunks.

## Document registry

Stored next to `index_status.json` as `document_registry.sqlite3`. Each row keeps:

- `workspace_id` / `source_id` / `document_id`
- `content_hash` (SHA-256 of file text)
- `revision` (monotonically increasing write generation)
- `status`: `active` | `writing` | `deleted` (tombstone)
- `observed_at` / `path`

## Inventory

Observed files are classified as:

| Kind | Meaning |
|------|---------|
| `new` | Not in registry (or only tombstoned) |
| `changed` | Hash differs, or a stuck `writing` row needs resume |
| `unchanged` | Same hash and `active` — **skip embeddings** |
| `deleted` | In registry as live, missing on disk |

For `index --files`, deletion detection is scoped to the requested paths only.

## Write–verify–retire

For each new/changed document:

1. Mark registry row `writing` and bump `revision`
2. Embed and upsert the new points
3. Verify points for that document/revision exist
4. Retire orphan point IDs for the document
5. Mark registry row `active`

If verification fails, the previous registry snapshot is restored and orphans are
not retired. Deleted files are removed from Qdrant only after inventory confirms
they are gone, then the registry row is tombstoned.

## CLI

`python -m rag.cli index --files path1 path2` runs this flow via
`rag.indexer.incremental.run_incremental`.
