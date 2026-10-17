# Migrating to workspace manifests

`workspace_manifests` is required. Configurations without at least one
`workspace.yaml` fail at registry load.

## Steps

1. Add a `workspace.yaml` (see [workspace-manifest.md](workspace-manifest.md)).
   Map former `index.knowledge` / `index.code` / `index.lis` globs to `roots[]`
   with types `architecture_docs`, `source_code`, and `policies` respectively.
2. Point `config.yaml` at the manifest(s):

   ```yaml
   workspace_manifests:
     - ./workspaces/my-app.yaml
   ```

3. Run a full `python -m rag.cli index` so payload schema v1 and
   `index_manifest.json` are written. Indexes with `payload_schema_version=0`
   are rejected until reindexed.
4. Switch clients to `list_workspaces` / `search` / `/api/v1` with explicit
   `workspace_id` when more than one workspace exists.
5. Before binding HTTP to a non-loopback host, configure `mcp.auth.tokens`.
6. Verify with `npm run rag:verify` and the [acceptance matrix](acceptance-matrix.md).

## Removed compatibility paths

- Synthetic workspace `id=default` derived from `index.*` alone
- Unfiltered Qdrant queries (`allow_legacy`)
- MCP tool `index_status` (use `get_index_status`)
- Config-dump `list_sources` without service-layer authz
