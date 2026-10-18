# Observability

## Lifecycle status

`get_index_status` / `GET /api/v1/index/status` include:

| Field | Values |
|-------|--------|
| `lifecycle` | `not_indexed` \| `indexing` \| `ready` \| `partial` \| `error` |
| `error_count` | Non-zero when lifecycle is `error` |
| `last_success_at` | From status file `updated_at` |
| `correlation_id` | Current request correlation id |

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /health` | Liveness (no bearer required) |
| `GET /ready` | Ready when lifecycle is `ready` or `partial` (else 503) |
| `GET /metrics` | Prometheus text; same auth as `/api/v1` (anonymous on loopback) |

## Correlation ID

Send `X-Correlation-ID`. If omitted, the server generates one and echoes it on
responses. Context is stored in a contextvar for service/store logs.

## Logging rules

`rag.observability.redact` strips API keys, bearer tokens, and private key
blocks. Document contents and credentials must never be logged.

HTTP auth failures (`missing_bearer` / `invalid_token`) are logged at warning
with peer and path only — never the raw token. See
[access-control.md](access-control.md).

## Embedding circuit breaker

`embedding.circuit_breaker_failures` / `circuit_breaker_seconds` open a
process-local breaker after consecutive embedding HTTP failures so search fails
fast with a clear error instead of hanging on a dead embedding server. Set either
value to `0` to disable.
