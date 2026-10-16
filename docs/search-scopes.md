# Search filters and scopes (Phase 10+)

Storage-layer search and delete helpers require a workspace boundary.

## Required workspace filter

`build_type_app_filter` / `VectorStore.search` require `workspace_id` unless
`allow_legacy=True` is set for single-default compatibility.

In multi-workspace mode, callers (and `search_hits`) must pass an explicit
`workspace_id`. Missing workspace raises `WorkspaceFilterError` / `ValueError`.

## Additional filters

| Filter | Payload field |
|--------|----------------|
| `source_id` | `source_id` |
| `document_id` | `document_id` |
| `language` | `language` |
| `type_filter` | `type` |
| `app_filter` | `app` (deprecated compatibility) |
| LIS fields | `doc_type`, `process_area`, `domain`, `status` |
| `requirement_id` | `requirement_ids` |

`path_prefix` remains a post-filter in `rag.retrieval.search` for compatibility.

## Scopes

| Scope | Behavior |
|------|----------|
| `workspace` (default) | Restrict to `workspace_id` |
| `source` | Require `source_id` in addition to workspace |
| `related` | Starting workspace + authorized outbound relationships |
| `global` | **Disabled** — raises `ScopeDisabledError` |

`related` expands via `RelationshipRegistry` and the caller's principal
allowlist. `global` stays disabled.
