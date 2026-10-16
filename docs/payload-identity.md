# Payload identity

## Rules

- Point IDs are derived from `workspace_id + source_id + document_id + chunk_key`.
- Content hash and revision are stored in payload, not in the point ID.
- `schema_version=1` marks the new payload. Legacy points use `schema_version=0`
  and keep the old content-including ID strategy for compatibility.
- The same relative path in two workspaces must never share a point ID.

## Migration

New indexing writes schema v1 payloads. Mixed active generations are forbidden;
legacy collections remain readable only in explicit legacy/single-workspace mode
until reindexed.
