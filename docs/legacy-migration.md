# Legacy to multi-workspace migration

1. Keep using `config.yaml` — a synthetic `default` workspace is derived.
2. Run a full `python -m rag.cli index` so payload schema v1 and
   `index_manifest.json` are written.
3. Add optional `workspace.yaml` manifests; validate with existing tests /
   startup loaders before pointing new roots at production data.
4. Switch clients to `list_workspaces` / `search` / `/api/v1` with explicit
   `workspace_id` when more than one workspace exists.
5. Before binding HTTP to a non-loopback host, configure `mcp.auth.tokens`.
6. Verify with `npm run rag:verify` and the [acceptance matrix](acceptance-matrix.md).
