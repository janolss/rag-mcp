# Search filters and scopes

Storage-layer search and delete helpers require a workspace boundary.

## Required workspace filter

`build_type_app_filter` / `VectorStore.search` require `workspace_id` for
`workspace` and `source` scopes. Missing workspace raises `WorkspaceFilterError`.

When exactly one workspace is registered, `search_hits` and services may infer
its id. Multi-workspace callers must pass `workspace_id` explicitly.

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
