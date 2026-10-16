# ADR 0001: Retain the Python runtime

## Status

Accepted

## Context

The multi-workspace plan originally recommended Node.js, TypeScript and Fastify.
The existing implementation is already a working single-workspace RAG/MCP service
written in Python 3.10+ with:

- official MCP TypeScript is not required because the Python MCP SDK is in use
- Starlette/Uvicorn for HTTP/SSE transports
- Qdrant via `qdrant-client`
- pytest-backed coverage for indexing, retrieval and MCP contracts

Rewriting the stack to Node.js would recreate working retrieval, transport and
test infrastructure without closing the highest-risk gaps: workspace isolation,
atomic indexing and stable identities.

## Decision

Keep Python as the runtime and language for the multi-workspace evolution.

Primary stack:

- Python 3.10+
- MCP Python SDK
- Starlette + Uvicorn for HTTP transports
- Qdrant
- Pydantic v2 for versioned manifests and API schemas
- SQLite (stdlib) for document registry, jobs and active-generation pointers
- Ruff for lint and format gates

## Consequences

Positive:

- Existing MCP tools, capability gating, LIS support and tests remain usable.
- Delivery focus stays on domain model, isolation and safe indexing.
- One process can still expose MCP and REST adapters over the same services.

Negative / accepted trade-offs:

- The architecture docs diverge from the original Node.js recommendation.
- Contributors need a Python toolchain rather than a Node-only workflow.

## Quality gate

Every pull request must pass:

```bash
npm run rag:verify
```

This runs Ruff check, Ruff format check and the full pytest suite.
