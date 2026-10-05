# Local workspace RAG MCP

This document describes the retrieval layer for coding agents. The
implementation lives in this package (`rag-mcp`).

## Goal

Help an MCP-compatible agent answer:

> Which parts of the system should I read to understand and change X?
> Which requirements apply, what is the impact, and where are the gaps?

## Pipeline

```text
configured knowledge + code globs (relative to workspace)
        → chunk (+ requirement_ids, start/end line)
        → embeddings (OpenAI-compatible or Ollama HTTP)
        → Qdrant (local file by default; server for teams)
        → MCP tools / resources / prompts
```

Provider-agnostic embeddings: configure `embedding.base_url` + `model` against
Ollama, LM Studio, Paddock, or any OpenAI-compatible `/v1/embeddings` server.

Sources, app labels, collection name, requirement ID patterns, and MCP
instructions are **config-driven** (`config.yaml` / `config.example.yaml`).

Typical layout:

```text
my-workspace/
  docs/ ...
  src/ ...
  rag-mcp/          ← this package (repo_root: "..")
```

### Tools

- `index_status()` — collection freshness, model, `git_sha`, stale hints
- `list_sources()` — apps, globs, patterns
- `search_knowledge(query, path_prefix?)` — documentation
- `search_code(query, app?, path_prefix?)` — source/tests
- `get_context_pack(task, app?)` — structured docs + code pack
- `trace_requirement(requirement, app?)` — ID/text → docs + code
- `impact_of_change(change, app?, path_prefix?)` — impact sections
- `find_gaps(area, app?)` — heuristic coverage gaps

Search applies optional **lexical re-rank**
(`search.vector_weight` / `search.lexical_weight`).

### Resources

- `rag://status`
- `rag://sources`

### Prompts

- `change-plan`, `pr-review`, `requirement-coverage`, `onboarding-slice`,
  `regression-check`

### Commands

From the package root (after venv setup):

- `npm run rag:index` / `python -m rag.cli index`
- `python -m rag.cli index --files path1 path2` — partial upsert
- `npm run rag:status`
- `npm run rag:mcp`
- `npm run rag:test`
- `npm run package` — build `dist/rag-mcp.zip` for reuse in other workspaces

Full index recreates the collection. Partial `--files` deletes+upserts points for
those paths only. The MCP server does not reindex on start.

### Team concurrency

- Prefer `qdrant.mode: server` + Compose when multiple agents share an index
- Index via CLI/CI; MCP clients are read-only consumers
- Use `index_status.git_sha` to detect stale indexes vs the working tree

## Follow-ups (not implemented)

- Sparse/BM25 hybrid (beyond lexical re-rank of vector candidates)
- AST-aware TypeScript chunking
- Full git-diff driven incremental indexing
- Knowledge-graph relations between chunks

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
