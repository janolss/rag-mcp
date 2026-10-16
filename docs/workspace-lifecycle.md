# Workspace lifecycle (Phase 2)

## Overview

A workspace is a stable logical project registered in the server. Phase 2
introduces the in-memory `WorkspaceRegistry` and a legacy adapter that maps the
existing single-repo `config.yaml` to a synthetic workspace with ID `default`.

## ID rules

- `workspace.id` must be non-empty and unique within the registry.
- IDs are stable keys used by later search, index and MCP contracts.
- Until manifests land (Phase 3), only the synthetic `default` workspace exists
  for legacy configurations.

## Legacy compatibility

`WorkspaceRegistry.from_config(config)` builds one workspace:

- `id`: `default`
- `root_path`: `config.repo_root_path`
- sources derived from enabled `knowledge` / `code` / `lis` buckets
- `legacy=True`

Existing CLI and MCP entrypoints remain unchanged. Multi-workspace APIs will
require an explicit `workspace_id` once more than one workspace is registered.

## Reload semantics

`replace_all()` swaps the registry contents atomically. A duplicate ID during
reload rejects the whole update and leaves the previous snapshot intact.
