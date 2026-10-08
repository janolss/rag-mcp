# Local workspace RAG MCP

This document describes the retrieval layer for coding agents. The
implementation lives in this package (`rag-mcp`).

## Goal

Help an MCP-compatible agent answer:

> Which parts of the system should I read to understand and change X?
> Which requirements apply, what is the impact, and where are the gaps?
> Which organizational LIS rules / instructions apply?

## Pipeline

```text
configured knowledge + code + optional lis globs
        → chunk (+ requirement_ids, start/end line; LIS frontmatter → payload)
        → embeddings (OpenAI-compatible or Ollama HTTP)
        → Qdrant (local file by default; server for teams)
        → MCP tools / resources / prompts (registered per mcp.capabilities)
```

Provider-agnostic embeddings: configure `embedding.base_url` + `model` against
Ollama, LM Studio, Paddock, or any OpenAI-compatible `/v1/embeddings` server.
Native Ollama uses `embedding.provider: ollama`.

Sources, capabilities, app labels, collection name, requirement ID patterns, MCP
instructions, and transport are **config-driven** (`config.yaml` /
`config.example.yaml`). Priority: CLI flags > `RAG_*` env vars > YAML > defaults.

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
- which MCP tools (and related prompts) are registered at server start

Empty/irrelevant tools are not exposed when a capability is off.

### Tools

- `index_status()` — collection freshness, model, `git_sha`, stale hints
- `list_sources()` — capabilities, apps, knowledge/code/lis globs, patterns
- `search_knowledge(query, path_prefix?)` — documentation (if capability on)
- `search_code(query, app?, path_prefix?)` — source/tests (if capability on)
- `search_lis(query, doc_type?, process_area?, domain?, status?, path_prefix?)` — LIS
- `get_context_pack(task, app?)` — structured pack from enabled sources
- `trace_requirement(requirement, app?)` — ID/text → docs + code (knowledge/code)
- `impact_of_change(change, app?, path_prefix?)` — impact sections
- `find_gaps(area, app?)` — heuristic coverage gaps

Search applies optional **lexical re-rank**
(`search.vector_weight` / `search.lexical_weight`).

### Resources

- `rag://status`
- `rag://sources`

### Prompts

When knowledge or code is enabled:

- `change-plan`, `pr-review`, `requirement-coverage`, `onboarding-slice`,
  `regression-check`

### Transports

| `mcp.transport` | How clients connect |
|-----------------|---------------------|
| `stdio` (default) | Cursor / VS Code spawn `run_mcp.py` |
| `streamable-http` | URL `http://host:port/mcp` (POST) |
| `sse` | Legacy SSE: GET `/sse`, POST `/messages/` |
| `http` | Dual: both `/mcp` and `/sse` on one port |

`npm run rag:mcp:http` starts dual HTTP on `127.0.0.1:8000`.
`stateless_http: true` (default) helps many URL clients.
Root `GET /` returns a JSON endpoint map.

Implementation: `rag/mcp_http.py` (uvicorn + Starlette apps from MCP SDK).

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

Full index recreates the collection. Partial `--files` deletes+upserts points for
those paths only. The MCP server does not reindex on start.

### Team concurrency

- Prefer `qdrant.mode: server` + Compose when multiple agents share an index
- Index via CLI/CI; MCP clients are read-only consumers
- Use `index_status.git_sha` to detect stale indexes vs the working tree
- Do not run two processes against `qdrant.mode: local` (stdio MCP + HTTP MCP + index)

## Follow-ups (not implemented)

- Sparse/BM25 hybrid (beyond lexical re-rank of vector candidates)
- AST-aware TypeScript chunking
- Full git-diff driven incremental indexing
- Knowledge-graph relations between chunks
- LIS compliance workflow tools (applicable rules / checklist) — discovery via
  `search_lis` only in the current surface
- Built-in PDF/Office → markdown sync for LIS (index a pre-synced mirror instead)

## Layout

```text
rag-mcp/
  rag/                 # config, embeddings, store, indexer, retrieval, MCP
    mcp_server.py      # tool registration + entry
    mcp_http.py        # HTTP / SSE / dual transport
    mcp_prompts.py
    indexer/           # walk, chunk, frontmatter, metadata, run
    retrieval/         # search, context_pack, trace, impact
  tests/
  scripts/package.sh
  config.example.yaml
  docker-compose.qdrant.yml   # optional server mode
  README.md
```
