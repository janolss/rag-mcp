# Local workspace RAG MCP (Step 1 MVP)

This document describes the retrieval layer for coding agents. The
implementation lives in this package (`rag-mcp`).

## Goal

Help an MCP-compatible agent answer:

> Which parts of the system should I read to understand and change X?

## MVP (implemented)

```text
configured knowledge + code globs (relative to workspace)
        → chunk
        → OpenAI-compatible embeddings (HTTP)
        → Qdrant (local file by default)
        → MCP: search_knowledge / search_code
```

Provider-agnostic embeddings: configure `embedding.base_url` + `model` against
Ollama, LM Studio, Paddock, or any OpenAI-compatible `/v1/embeddings` server.

Sources, app labels, collection name, and MCP instructions are **config-driven**
(`config.yaml` / `config.example.yaml`). Typical layout:

```text
my-workspace/
  docs/ ...
  src/ ...
  rag-mcp/          ← this package (repo_root: "..")
```

### Tools

- `search_knowledge(query)` — documentation (`type=documentation`)
- `search_code(query, app?)` — source/tests; optional `app` from `index.apps`

### Commands

From the package root (after venv setup):

- `npm run rag:index` / `python -m rag.cli index`
- `npm run rag:status`
- `npm run rag:mcp`
- `npm run rag:test`
- `npm run package` — build `dist/rag-mcp.zip` for reuse in other workspaces

Index is a full rebuild via CLI. The MCP server does not reindex on start.

## Out of scope for MVP

- Hybrid keyword / symbol search
- Reranking
- AST-aware TypeScript chunking
- Incremental / git-diff indexing
- Knowledge-graph relations between chunks

Those are Steg 2–3 follow-ups.

## Layout

```text
rag-mcp/
  rag/           # Python package
  tests/
  scripts/package.sh
  config.example.yaml
  docker-compose.qdrant.yml   # optional server mode
  README.md
```
