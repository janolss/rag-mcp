# Source model

## Contract

Each workspace owns one or more `Source` objects:

- `id`: unique within the workspace
- `type`: document type (`source_code`, `architecture_docs`, ...)
- `root`: absolute/normalized root path
- `include` / `exclude`: glob patterns
- `adapter`: extractor name (`filesystem` by default)
- `status`: `not_indexed|indexing|ready|partial|error`
- `bucket`: optional derived classification (`knowledge|code|lis`)

## Indexing

`python -m rag.cli index` walks every registered `Source` root (manifest or
legacy) and stamps `workspace_id` / `source_id` on each chunk. Path security
keeps reads inside declared roots.

Path identity (`file`) is relative to the workspace root when possible, then
the source root — **not** `config.index.repo_root`. That keeps `index.apps`
prefixes such as `apps/web/` matching even when the project lives outside the
RAG package directory. Reindex after upgrading so old absolute `file` / `app:
global` chunks are replaced.

```bash
# Index every registered workspace (staging rebuild of the shared collection)
python -m rag.cli index

# Index one workspace without wiping peer workspaces
python -m rag.cli index --workspace-id lk_apps

# Partial upsert for one workspace
python -m rag.cli index --workspace-id lk_apps --files apps/api/main.ts
```

## Legacy mapping

When no manifests are configured, enabled `index.knowledge` / `index.code` /
`index.lis` globs become sources named `knowledge`, `code` and `lis` under the
synthetic `default` workspace. Indexing uses the same Source walker.
