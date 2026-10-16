# Observability (Phase 17)

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
| `GET /health` | Liveness |
| `GET /ready` | Ready when lifecycle is `ready` or `partial` (else 503) |
| `GET /metrics` | Prometheus text counters/latency |

## Correlation ID

Send `X-Correlation-ID`. If omitted, the server generates one and echoes it on
responses. Context is stored in a contextvar for service/store logs.

## Logging rules

`rag.observability.redact` strips API keys, bearer tokens, and private key
blocks. Document contents and credentials must never be logged.
