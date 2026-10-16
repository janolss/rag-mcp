# MCP contracts (Phase 12)

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

`search_knowledge`, `search_code`, `search_lis`, `index_status`, analysis tools,
and prompts are unchanged for clients. Prefer the new tools for multi-workspace.

## Workspace resolution

- Exactly one workspace (typically synthetic `default`): `workspace_id` may be omitted.
- Multiple workspaces: callers must pass `workspace_id` or tools return an error.

## Client migration

1. Call `list_workspaces` / `get_workspace_info` to discover ids.
2. Pass `workspace_id` into `search`, `get_document`, and `get_index_status`.
3. Keep using capability-gated legacy search tools until clients are updated.
