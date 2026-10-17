# Workspace lifecycle

## Overview

A workspace is a stable logical project registered via `workspace.yaml`
manifests listed in `config.workspace_manifests` (at least one required).

## ID rules

- `workspace.id` must be non-empty and unique within the registry.
- IDs are stable keys used by search, index and MCP contracts.

## Loading

`WorkspaceRegistry.from_config(config)` loads every path in
`workspace_manifests`. An empty list raises `WorkspaceConfigError`.

CLI `index` / `search` / `status` accept `--workspace-id`. Multi-workspace MCP
and REST callers must pass `workspace_id` once more than one workspace is
registered. Indexing walks each workspace's declared `Source` roots.

## Reload semantics

`replace_all()` swaps the registry contents atomically. A duplicate ID during
reload rejects the whole update and leaves the previous snapshot intact.
