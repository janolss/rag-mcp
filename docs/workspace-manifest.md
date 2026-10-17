# Workspace manifest

Versioned `workspace.yaml` files describe registered workspaces.

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

`workspace_manifests` must contain at least one path. See
[legacy-migration.md](legacy-migration.md) if you previously relied on
`index.*` globs alone.

## Examples

See:

- `examples/workspaces/lk_apps.yaml`
- `examples/workspaces/shared-auth.yaml`
- `docs/schemas/workspace-manifest.schema.json`
