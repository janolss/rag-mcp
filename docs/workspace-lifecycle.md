# Workspace lifecycle

## Overview

A workspace is a stable logical project registered in the server. The
in-memory `WorkspaceRegistry` and a legacy adapter map the existing
single-repo `config.yaml` to a synthetic workspace with ID `default`.

## ID rules

- `workspace.id` must be non-empty and unique within the registry.
- IDs are stable keys used by later search, index and MCP contracts.
- Until manifests land, only the synthetic `default` workspace exists
  for legacy configurations.

## Legacy compatibility

`WorkspaceRegistry.from_config(config)` builds one workspace:

- `id`: `default`
- `root_path`: `config.repo_root_path`
- sources derived from enabled `knowledge` / `code` / `lis` buckets
- `legacy=True`

CLI `index` / `search` / `status` accept `--workspace-id`. Multi-workspace MCP
and REST callers must pass `workspace_id` once more than one workspace is
registered. Indexing walks each workspace's declared `Source` roots.

## Reload semantics

`replace_all()` swaps the registry contents atomically. A duplicate ID during
reload rejects the whole update and leaves the previous snapshot intact.
