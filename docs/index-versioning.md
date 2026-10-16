# Index versioning (Phase 18)

After a successful full index the server writes `index_manifest.json` next to
`index_status.json` with:

- `payload_schema_version`
- `chunker_version`
- `indexing_version`
- `embedding_model`
- `vector_size`
- `collection`

Partial updates refuse to write when the existing manifest is incompatible.
Legacy schema v0 indexes are treated as read-only until a full reindex migrates
them through a new generation.
