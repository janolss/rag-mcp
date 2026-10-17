# Access control

## Defaults

- `stdio` and loopback HTTP (`127.0.0.1` / `localhost`) use a local anonymous
  principal.
- Binding HTTP to a non-loopback host **refuses to start** unless
  `mcp.auth.tokens` is configured.
- On a non-loopback bind, every request (REST and MCP transports) requires a
  valid `Authorization: Bearer` token matching `mcp.auth.tokens`.

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

- HTTP (REST `/api/v1` and MCP `/mcp`, `/sse`, `/messages/`): same
  `BearerAuthMiddleware` on the Starlette app
- Services and retrieval: workspace/source allowlists on `Principal` for
  list/get workspace, sources, search, documents, and index status
- MCP stdio remains local-anonymous

`/health` stays reachable without a bearer token for probes. `/metrics` follows
the same auth rules as `/api/v1` (anonymous on loopback; bearer on public binds).

HTTP also enforces `mcp.max_body_bytes` (413) and, on non-loopback binds,
`mcp.rate_limit_per_minute` (429; `0` disables).
