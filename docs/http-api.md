# HTTP API `/api/v1` (Phase 13)

REST endpoints share `rag.services.ServiceApp` with MCP tools so domain results
match for the same inputs. MCP transports (`/mcp`, `/sse`, `/messages/`) are
unchanged.

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1` | Discovery |
| GET | `/api/v1/workspaces` | `?query=` `?tag=` |
| GET | `/api/v1/workspaces/{id}` | Detail |
| GET | `/api/v1/workspaces/{id}/sources` | Sources |
| POST | `/api/v1/search` | JSON body (`SearchRequest`) |
| GET | `/api/v1/documents` | `source_id`, `document_id`, optional lines |
| GET | `/api/v1/index/status` | Optional `workspace_id` / `source_id` |

## Search body

```json
{
  "query": "booking flow",
  "workspace_id": "default",
  "source_ids": ["knowledge"],
  "document_types": ["documentation"],
  "limit": 8,
  "scope": "workspace",
  "search_mode": "semantic"
}
```

## Errors

JSON `{ "error": "...", "code": "not_found|validation_error|workspace_required|..." }`
with HTTP 400/404/500.

## curl examples

```bash
curl -s http://127.0.0.1:8000/api/v1/workspaces
curl -s http://127.0.0.1:8000/api/v1/workspaces/default/sources
curl -s -X POST http://127.0.0.1:8000/api/v1/search \
  -H 'content-type: application/json' \
  -d '{"query":"auth","workspace_id":"default"}'
```

## Versioning

Path prefix `/api/v1` is stable for this release train. Additive fields may appear;
breaking changes require `/api/v2`.
