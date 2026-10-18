# Access control

## Defaults

- `stdio` and loopback HTTP peers (`127.0.0.1` / `localhost` / `::1`) use a
  local anonymous principal unless `mcp.auth.require_auth_always` is true.
- Binding HTTP to a non-loopback host **refuses to start** unless
  `mcp.auth.tokens` and/or `mcp.auth.oauth` is configured (when
  `require_auth_for_public_bind` is true).
- On a non-loopback peer (or when `require_auth_always` is true), every request
  (REST and MCP transports) requires a valid `Authorization: Bearer` token.

Anonymous policy prefers the **peer client IP** from the ASGI scope. If the
peer is missing, the configured bind host is used as a fallback. Behind a
reverse proxy on the same host, enable `require_auth_always: true` so
loopback peers still require a bearer token.

## Static API tokens

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

## OAuth / OIDC (MCP discovery)

Optional resource-server mode against an **external** authorization server
(Entra ID, Okta, Keycloak, etc.). The MCP Python SDK mounts Protected Resource
Metadata and issues `WWW-Authenticate` challenges with `resource_metadata` so
clients such as Cursor can discover where to obtain a token.

```yaml
mcp:
  host: 0.0.0.0
  transport: http
  auth:
    oauth:
      enabled: true
      issuer_url: "https://login.microsoftonline.com/<tenant-id>/v2.0"
      audience: "api://<app-id>"          # or Application ID URI
      # resource_server_url: "https://rag.example.com/mcp"  # defaults to public /mcp URL
      # jwks_uri: ""   # discovered via OpenID configuration when omitted
      # required_scopes: ["access_as_user"]
    # Static tokens still work alongside OAuth (CI / break-glass):
    # tokens:
    #   - name: ci
    #     token_hash: "..."
```

Env: `RAG_MCP_OAUTH_ENABLED`, `RAG_MCP_OAUTH_ISSUER`, `RAG_MCP_OAUTH_AUDIENCE`,
`RAG_MCP_OAUTH_JWKS_URI`, `RAG_MCP_OAUTH_RESOURCE`.

Valid JWTs become principals with full workspace/source access by default
(same semantics as an empty allowlist on a static token). Configure IdP app
roles/scopes separately if you need finer control at the identity provider.

### Cursor + Entra ID (sketch)

1. Register an app in Entra; expose an API (`audience` / Application ID URI).
2. Allow Cursor redirect URIs on the app:
   - `http://localhost:8787/callback` (desktop)
   - `https://www.cursor.com/agents/mcp/oauth/callback` (web/agents)
3. Create a client (public/PKCE) Cursor will use; put static OAuth client
   credentials in `mcp.json` when Dynamic Client Registration is unavailable:

```json
{
  "mcpServers": {
    "workspace-rag": {
      "url": "https://rag.example.com/mcp",
      "auth": {
        "CLIENT_ID": "<entra-app-client-id>",
        "scopes": ["api://<app-id>/.default"]
      }
    }
  }
}
```

4. Point `mcp.auth.oauth` at the tenant issuer and audience; restart HTTP MCP.

## Enforcement

- HTTP REST `/api/v1`: `BearerAuthMiddleware` (static tokens and/or JWT).
- HTTP MCP `/mcp`, `/sse`, `/messages/`: same static-token middleware when OAuth
  is off; when OAuth is on, the MCP SDK auth stack owns those paths (plus
  `/.well-known/oauth-protected-resource/...`).
- Services and retrieval: workspace/source allowlists on `Principal`.
- MCP stdio remains local-anonymous unless you only use HTTP auth settings for
  remote clients.

`/health` and `/.well-known/*` stay reachable without a bearer token.
`/metrics` follows the same auth rules as `/api/v1`.

HTTP also enforces `mcp.max_body_bytes` (413) and, on non-loopback peers (or
when `require_auth_always` is set), `mcp.rate_limit_per_minute` (429; `0`
disables).

## Audit logging

Failed bearer authentication logs a warning with peer, path, and reason
(`missing_bearer` / `invalid_token`). Raw tokens are never logged. Successful
auth is logged at debug with subject and path.
