# Access control

## Defaults

- `stdio` and loopback HTTP peers (`127.0.0.1` / `localhost` / `::1`) use a
  local anonymous principal unless `mcp.auth.require_auth_always` is true.
- Binding HTTP to a non-loopback host **refuses to start** unless
  `mcp.auth.tokens` is configured (when `require_auth_for_public_bind` is true).
- On a non-loopback peer (or when `require_auth_always` is true), every request
  (REST and MCP transports) requires a valid `Authorization: Bearer` token
  matching `mcp.auth.tokens`.

Anonymous policy prefers the **peer client IP** from the ASGI scope. If the
peer is missing, the configured bind host is used as a fallback. Behind a
reverse proxy on the same host, enable `require_auth_always: true` so
loopback peers still require a bearer token.

## Config

```yaml
mcp:
  host: 0.0.0.0
  auth:
    require_auth_for_public_bind: true
    require_auth_always: false   # set true behind a reverse proxy
    tokens:
      - name: ci
        token_hash: "<sha256 hex of raw token>"
        workspaces: ["default"]
        sources: ["knowledge", "code"]
```

Raw `token` values in config are hashed at load time; prefer storing only
`token_hash`. Rotate by adding a new token entry and removing the old hash.

Env: `RAG_MCP_REQUIRE_AUTH_ALWAYS=true`.

### Allowlists

After a successful token match:

- Omitted or empty `workspaces` / `sources` means **full access** (same as
  listing `"*"`). Prefer an explicit list or `"*"` so intent is obvious.
- Non-empty lists restrict the principal to those workspace/source ids
  (or `"*"` as a wildcard entry).

## Enforcement

- HTTP (REST `/api/v1` and MCP `/mcp`, `/sse`, `/messages/`): same
  `BearerAuthMiddleware` on the Starlette app
- Services and retrieval: workspace/source allowlists on `Principal` for
  list/get workspace, sources, search, documents, and index status
- MCP stdio remains local-anonymous unless `require_auth_always` is set
  (HTTP only; stdio has no bearer path)

`/health` stays reachable without a bearer token for probes. `/metrics` follows
the same auth rules as `/api/v1` (anonymous on loopback peers; bearer on public
peers or when `require_auth_always` is set).

HTTP also enforces `mcp.max_body_bytes` (413) and, on non-loopback peers (or
when `require_auth_always` is set), `mcp.rate_limit_per_minute` (429; `0`
disables).
