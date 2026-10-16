# Access control (Phase 16)

## Defaults

- `stdio` and loopback HTTP (`127.0.0.1` / `localhost`) use a local anonymous
  principal.
- Binding HTTP to a non-loopback host **refuses to start** unless
  `mcp.auth.tokens` is configured.

## Config

```yaml
mcp:
  host: 0.0.0.0
  auth:
    require_auth_for_public_bind: true
    tokens:
      - name: ci
        token_hash: "<sha256 hex of raw token>"
        workspaces: ["default"]
        sources: ["knowledge", "code"]
```

Raw `token` values in config are hashed at load time; prefer storing only
`token_hash`. Rotate by adding a new token entry and removing the old hash.

## Enforcement

- REST: `Authorization: Bearer …` via `BearerAuthMiddleware`
- Services: workspace/source allowlists on `Principal`
- MCP stdio remains local-anonymous; HTTP MCP shares the same bind guard

`/health` and `/metrics` stay reachable without a bearer token for probes.
