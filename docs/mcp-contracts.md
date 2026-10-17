# MCP contracts

Workspace-aware tools sit on a shared application service layer
(`rag.services.ServiceApp`). MCP and REST adapters call the same services.

## Tools

| Tool | Purpose |
|------|---------|
| `list_workspaces` | List registered workspaces (`query`, `tags`) |
| `get_workspace_info` | Detailed workspace + sources + relationships |
| `list_sources` | With `workspace_id`: sources for that workspace; without: sources grouped by visible workspaces |
| `search` | Structured hits via `SearchService` (`semantic` \| `keyword` \| `hybrid`) |
| `get_document` | Secure file read with optional line range |
| `get_index_status` | Structured status with optional workspace/source |
| `search_knowledge` / `search_code` / `search_lis` | Capability-gated text search via services |
| `get_context_pack` / `trace_requirement` / `impact_of_change` / `find_gaps` | Analysis tools via `ServiceApp.analysis` |

Resources `rag://status` and `rag://sources` use the same services (JSON `ok` envelope).

Convenience search tools keep **text** hit formatting; prefer `search` for
structured multi-workspace clients.

## Workspace resolution

- Exactly one registered workspace: `workspace_id` may be omitted and is inferred.
- Multiple workspaces: callers must pass `workspace_id` or tools return an error.
- Workspaces come from `workspace_manifests` (see [workspace-manifest.md](workspace-manifest.md)).

## Client migration

1. Call `list_workspaces` first to discover ids (default MCP instructions lead
   with this before status/search).
2. Call `get_workspace_info` / `list_sources(workspace_id)`, then
   `get_index_status`.
3. Pass `workspace_id` into `search`, `search_knowledge` / `search_code` /
   `search_lis`, `get_document`, and `get_index_status` when more than one
   workspace is registered.
4. With a single manifest workspace, search tools work without an explicit id.
