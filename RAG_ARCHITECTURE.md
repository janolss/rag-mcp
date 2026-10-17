# Local workspace RAG MCP

This document describes the retrieval layer for coding agents. The
implementation lives in this package (`rag-mcp`).

## Runtime decision

The stack is Python 3.10+ (MCP SDK, Starlette/Uvicorn, Qdrant, Pydantic, Ruff).
See [docs/adr/0001-python-runtime.md](docs/adr/0001-python-runtime.md).

MCP and HTTP adapters share `rag.services.ServiceApp` (protocols in
`rag/services/contracts.py`). Workspaces come from required
`workspace_manifests` entries (at least one `workspace.yaml`).

## Goal

Help an MCP-compatible agent answer:

> Which parts of the system should I read to understand and change X?
> Which requirements apply, what is the impact, and where are the gaps?
> Which organizational LIS rules / instructions apply?

## Pipeline

```text
workspace sources (manifest roots)
        → adapters (markdown/filesystem; optional pdf/docx)
        → chunk (+ requirement_ids, line ranges; LIS frontmatter → payload)
        → embeddings (OpenAI-compatible or Ollama HTTP)
        → Qdrant (+ optional SQLite FTS5 lexical index)
        → MCP tools / resources / prompts + REST /api/v1
```

Provider-agnostic embeddings: configure `embedding.base_url` + `model` against
Ollama, LM Studio, Paddock, or any OpenAI-compatible `/v1/embeddings` server.
Native Ollama uses `embedding.provider: ollama`.

Sources, capabilities, app labels, collection name, requirement ID patterns, MCP
instructions, transport, and auth are **config-driven** (`config.yaml` /
`config.example.yaml`). Priority: CLI flags > `RAG_*` env vars > YAML > defaults.

### Workspaces

- One or more YAML manifests via `workspace_manifests` (see
  [docs/workspace-manifest.md](docs/workspace-manifest.md)).
- Isolation is enforced in the vector store filters and via principal
  allowlists when HTTP auth is active ([docs/access-control.md](docs/access-control.md)).
- Relationships between workspaces are declared on manifests and used for
  `scope=related` (see [docs/relationships.md](docs/relationships.md)).
  `scope=global` stays disabled until an explicit cross-tenant policy exists.

### Source types

| Bucket (`index.*` / capability) | Payload `type` | Role |
|---------------------------------|----------------|------|
| `knowledge` | `documentation` | Workspace docs, ADRs, requirements |
| `code` | `code` / `test` | Application source and tests |
| `lis` | `lis` | Org-wide ledningssystem (policies → mallar) |

Effective index buckets = `index.sources` ∩ `mcp.capabilities`.
`index.sources`: `knowledge` | `code` | `lis` | `all` | comma-separated.

LIS globs may be absolute (mirror outside the workspace). Markdown frontmatter
fields (`id`→`document_id`, `doc_type`, `process_area`, `domain`, `status`,
`title`) are stored on chunks for filtered `search_lis`.

Typical layout:

```text
my-workspace/
  docs/ ...
  src/ ...
  rag-mcp/          ← this package (repo_root: "..")
```

### Capabilities

`mcp.capabilities.{knowledge,code,lis}` gates:

- which globs are walked at index time
- which capability-scoped MCP tools (and related prompts) are registered

Empty/irrelevant tools are not exposed when a capability is off.

### Tools

Workspace / status (always registered):

- `list_workspaces(query?, tags?)`
- `get_workspace_info(workspace_id)`
- `get_index_status(workspace_id?, source_id?)`
- `list_sources(workspace_id?)` — sources for one workspace, or all visible workspaces
- `search(...)` — service-layer search (`semantic` | `keyword` | `hybrid`)
- `get_document(source_id, document_id, workspace_id?, start_line?, end_line?)`

Capability-gated:

- `search_knowledge(query, path_prefix?, workspace_id?, top_k?)`
- `search_code(query, app?, path_prefix?, workspace_id?, top_k?)`
- `search_lis(query, …filters, workspace_id?, top_k?)`
- `get_context_pack(task, app?, workspace_id?)`
- `trace_requirement(requirement, app?, workspace_id?)`
- `impact_of_change(change, app?, path_prefix?, workspace_id?)`
- `find_gaps(area, app?, workspace_id?)`

Search modes ([docs/hybrid-search.md](docs/hybrid-search.md)):

- `semantic` — Qdrant vectors (+ optional lexical re-rank of vector candidates)
- `keyword` — SQLite FTS5
- `hybrid` — both + reciprocal rank fusion

### Resources

- `rag://status` — JSON `{ok, ...}` (errors: `{ok: false, error}`)
- `rag://sources` — JSON `{ok, ...}`

### Prompts

When knowledge or code is enabled:

- `change-plan`, `pr-review`, `requirement-coverage`, `onboarding-slice`,
  `regression-check`

### Transports and HTTP API

| `mcp.transport` | How clients connect |
|-----------------|---------------------|
| `stdio` (default) | Cursor / VS Code spawn `run_mcp.py` |
| `streamable-http` | URL `http://host:port/mcp` (POST) |
| `sse` | Legacy SSE: GET `/sse`, POST `/messages/` |
| `http` | Dual: both `/mcp` and `/sse` on one port |

The same Starlette app also mounts REST `/api/v1` (workspaces, sources, search,
documents, index status) plus `/health`, `/ready`, `/metrics`. Root `GET /`
returns a JSON endpoint map.

`npm run rag:mcp:http` starts dual HTTP on `127.0.0.1:8000`.
`stateless_http: true` (default) helps many URL clients.

Loopback/stdio use an anonymous principal. Non-loopback binds require
`mcp.auth.tokens`; bearer auth covers REST and MCP paths. See
[docs/access-control.md](docs/access-control.md) and
[docs/http-api.md](docs/http-api.md).

Implementation: `rag/mcp_http.py`, `rag/http_api.py`, `rag/security/`.

### Indexing

- Full rebuild writes to a staging collection then activates
  ([docs/atomic-indexing.md](docs/atomic-indexing.md)).
- Partial `index --files` uses inventory/hash registry upserts
  ([docs/incremental-indexing.md](docs/incremental-indexing.md)).
- Path security: registered roots, symlink policy, size limits, secret denylist
  ([docs/path-security.md](docs/path-security.md)).
- Code chunking: size windows by default; optional tree-sitter for Python/JS/TS
  when `.[parsers]` is installed.
- Optional `.[formats]` for PDF/DOCX adapters (pre-synced files under a root).

The MCP server does not reindex on start.

### Commands

From the package root (after venv setup):

- `npm run rag:index` / `python -m rag.cli index`
- `python -m rag.cli index --files path1 path2` — partial upsert
- `npm run rag:status`
- `npm run rag:mcp` — stdio
- `npm run rag:mcp:http` — dual HTTP
- `python -m rag.mcp_server --transport http --port 8000`
- `python -m rag.cli search "…" --mode knowledge|code|lis`
- `npm run rag:test`
- `npm run package` — build `dist/rag-mcp.zip`

### Team concurrency

- Prefer `qdrant.mode: server` + Compose when multiple agents share an index
- Index via CLI/CI; MCP clients are read-only consumers
- Use `get_index_status` / `git_sha` to detect stale indexes
- Do not run two processes against `qdrant.mode: local` (stdio MCP + HTTP MCP + index)

## Follow-ups (not implemented)

- Sparse/BM25 lexical scoring inside Qdrant (keyword path uses SQLite FTS5 today)
- Knowledge-graph relations between chunks (workspace relationships exist;
  chunk-level graphs do not)
- LIS compliance workflow tools (applicable rules / checklist) — discovery via
  `search_lis` only in the current surface
- Built-in remote LIS sync (index a pre-synced local mirror; optional pdf/docx
  extractors only)

## Layout

```text
rag-mcp/
  rag/
    mcp_server.py      # tool registration + entry
    mcp_http.py        # HTTP / SSE / dual transport
    http_api.py        # REST /api/v1 + middleware
    config.py
    embeddings.py
    store.py
    runtime.py
    security/          # paths, bearer auth, access policy
    services/          # ServiceApp (workspaces, search, documents, …)
    workspaces/        # manifests, registry
    domain/            # Workspace / Source models
    adapters/          # markdown, filesystem, optional pdf/docx
    indexer/           # walk, chunk, inventory, atomic/incremental run
    retrieval/         # search, lexical, context_pack, trace, impact
    relationships/     # workspace relationship expansion
  docs/
  tests/
  scripts/package.sh
  config.example.yaml
  docker-compose.qdrant.yml
  README.md
```
