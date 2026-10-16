# Workspace manifest

Phase 3 introduces versioned `workspace.yaml` files.

## Schema

- `schema_version`: currently `1`
- `id`: stable unique workspace ID
- `name`: human-readable name
- `roots[]`: sources with unique `id`, `path`, `type`, optional include/exclude
- `relationships[]`: typed links to other workspaces
- `instructions`, `technologies`, `tags`: project context (treated as data)

Unknown fields are rejected. Duplicate root IDs and unsupported relationship
types fail validation before any file indexing occurs.

## Configuration

```yaml
workspace_manifests:
  - ./workspaces/lk_apps.yaml
  - ./workspaces/shared-auth.yaml
```

If `workspace_manifests` is empty or omitted, the server keeps the legacy
synthetic `default` workspace from `config.yaml`.

## Examples

See:

- `examples/workspaces/lk_apps.yaml`
- `examples/workspaces/shared-auth.yaml`
- `docs/schemas/workspace-manifest.schema.json`
