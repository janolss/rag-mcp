# Multi-workspace acceptance matrix

| # | Requirement | Code | Tests | Status |
|---|-------------|------|-------|--------|
| 1 | Python runtime + quality gate | `pyproject.toml`, `rag:verify` | `test_entrypoint_smoke` | pass |
| 2 | Workspace model + registry | `rag/domain`, `rag/workspaces` | `test_domain_models`, `test_workspace_registry` | pass |
| 3 | Versioned manifests | `rag/workspaces/manifest.py` | `test_workspace_manifest` | pass |
| 4 | Explicit sources | `rag/indexer/source_model.py` | `test_source_model` | pass |
| 5 | Stable identities / payload | `rag/indexer/identity.py`, `payload.py` | `test_identity`, `test_payload_schema` | pass |
| 6 | Atomic full reindex | `rag/indexer/collections.py` | `test_atomic_reindex` | pass |
| 7 | Incremental inventory | `document_registry`, `inventory`, `incremental` | `test_incremental_*` | pass |
| 8 | Structural chunking | `rag/indexer/languages/` | `test_language_chunking` | pass |
| 9 | Keyword + hybrid search | `lexical.py`, `fusion.py` | `test_hybrid_search` | pass |
| 10 | Workspace filters/scopes | `rag/store.py` | `test_workspace_isolation` | pass |
| 11 | Relationships / related scope | `rag/relationships/` | `test_relationships` | pass |
| 12 | MCP service layer | `rag/services/`, `mcp_server.py` | `test_service_layer`, `test_mcp_workspace_tools` | pass |
| 13 | REST `/api/v1` parity | `rag/http_api.py` | `test_http_api` | pass |
| 14 | Index job coordination | `rag/indexer/jobs.py` | `test_index_jobs` | pass |
| 15 | Path security | `rag/security/paths.py` | path security tests | pass |
| 16 | Access control | `rag/security/access.py` | `test_access_control` | pass |
| 17 | Observability | `rag/observability.py` | `test_observability` | pass |
| 18 | Index versioning | `index_manifest.py` | versioning tests | pass |
| 19 | Format adapters | `rag/adapters/` | `test_adapters` | pass |
| 20 | Cross-cutting acceptance | this matrix + below | `test_acceptance_*` | pass |

## Legacy migration

1. Keep single-workspace `config.yaml` (synthetic `default`).
2. Run full `index` to build payload schema v1 + index manifest.
3. Optionally add `workspace.yaml` manifests and reindex.
4. Enable HTTP auth before non-loopback binds.
