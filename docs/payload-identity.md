# Payload identity

## Rules

- Point IDs are derived from `workspace_id + source_id + document_id + chunk_key`.
- Content hash and revision are stored in payload, not in the point ID.
- Indexed payloads use `schema_version=1`. Collections with
  `payload_schema_version=0` (or missing `index_manifest.json`) must be fully
  reindexed before incremental updates.
- The same relative path in two workspaces must never share a point ID.

## Migration

New indexing writes schema v1 payloads and `index_manifest.json`. Mixed active
generations are forbidden; run a full `python -m rag.cli index` after upgrades
that change payload schema, chunker, or embedding model.
