# MCP contracts

Workspace-aware tools sit on a shared application service layer
(`rag.services.ServiceApp`). Legacy tools remain as wrappers during migration.

## New tools

| Tool | Purpose |
|------|---------|
| `list_workspaces` | List registered workspaces (`query`, `tags`) |
| `get_workspace_info` | Detailed workspace + sources + relationships |
| `list_sources` | With `workspace_id`: sources for that workspace; without: legacy summary |
| `search` | Structured hits via `SearchService` (semantic mode) |
| `get_document` | Secure file read with optional line range |
| `get_index_status` | Structured status with optional workspace/source |

## Legacy wrappers

`search_knowledge`, `search_code`, and `search_lis` accept optional `workspace_id`
and use the same auto-resolve rules as `search`. Prefer the new tools for
structured multi-workspace clients; keep the convenience tools for capability-
gated single-bucket searches.

## Workspace resolution

- Exactly one workspace (synthetic `default` **or** a single manifest id such as
  `lk_apps`): `workspace_id` may be omitted and is inferred.
- Multiple workspaces: callers must pass `workspace_id` or tools return an error.

## Client migration

1. Call `list_workspaces` first to discover ids (default MCP instructions lead
   with this before status/search).
2. Call `get_workspace_info` / `list_sources(workspace_id)`, then
   `get_index_status`.
3. Pass `workspace_id` into `search`, `search_knowledge` / `search_code` /
   `search_lis`, `get_document`, and `get_index_status` when more than one
   workspace is registered.
4. With a single manifest workspace, legacy search tools work without an
   explicit id (same as `search`).
