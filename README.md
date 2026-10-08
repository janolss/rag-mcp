# rag-mcp

Local retrieval for coding agents. Indexes a workspace into Qdrant and exposes
MCP tools for search, context packs, requirement tracing, impact analysis, plus
prompts and resources for change/review workflows.

Place this package as `<workspace>/rag-mcp/`. Configure what to index in
`config.yaml`, then point Cursor / VS Code / OpenCode at `run_mcp.py`.

Embeddings support two HTTP styles via `embedding.provider`:

| provider | Endpoint | Typical servers |
|----------|----------|-----------------|
| `openai` (default) | `{base}/v1/embeddings` | LM Studio, Paddock, OpenAI-compatible |
| `ollama` | `{base}/api/embeddings` | Ollama native (`prompt` body) |

For Ollama batched embeddings, set `base_url: "http://localhost:11434/api/embed"`.

## Requirements

- Python 3.10+
- A local embedding server (OpenAI-compatible **or** Ollama native)
- Qdrant: default **local file** mode (no Docker). Optional server via Compose.

## Quick start (from zip or git clone)

1. Unpack / copy into your workspace as `rag-mcp/`:

```text
my-workspace/
  ...
  rag-mcp/          ← this package
    config.example.yaml
    run_mcp.py
    ...
```

2. Install dependencies:

```bash
cd rag-mcp
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. Configure:

```bash
cp config.example.yaml config.yaml
```

Edit at least:

- `embedding.*` — your local embedding endpoint
- `qdrant.collection` — unique name per workspace
- `index.repo_root` — default `".."` (parent workspace)
- `index.knowledge` / `index.code` / optional `index.lis` — globs (LIS may be absolute)
- `index.apps` — optional path-prefix → app labels for `search_code(app=...)`
- `mcp.capabilities` — which surfaces are active (`knowledge` / `code` / `lis`)
- `mcp.name` / `mcp.instructions` — how the agent should use the tools
- `mcp.transport` — `stdio` (default) or HTTP for URL clients (see below)

4. Index (full rebuild):

```bash
.venv/bin/python -m rag.cli --config config.yaml index
```

Partial upsert (does not recreate the collection):

```bash
.venv/bin/python -m rag.cli --config config.yaml index --files docs/requirements/booking.md apps/web/services/BookingService.ts
```

After large refactors, prefer a full `index`.

5. Add an MCP server (use **absolute** paths; no spaces in paths):

```json
{
  "mcpServers": {
    "workspace-rag": {
      "command": "/ABS/PATH/my-workspace/rag-mcp/.venv/bin/python",
      "args": ["/ABS/PATH/my-workspace/rag-mcp/run_mcp.py"],
      "env": {
        "RAG_CONFIG": "config.yaml"
      }
    }
  }
}
```

Verify:

```bash
ls /ABS/PATH/my-workspace/rag-mcp/.venv/bin/python
/ABS/PATH/my-workspace/rag-mcp/.venv/bin/python /ABS/PATH/my-workspace/rag-mcp/run_mcp.py
```

The second command should start the MCP server and wait on stdio — stop with Ctrl+C.

Start MCP only after a successful `index`. MCP does **not** reindex on startup.

### Cursor / VS Code / OpenCode (stdio)

Same stdio command works across clients. Put the JSON block above in:

- **Cursor** — MCP settings (`mcp.json` / Cursor Settings → MCP)
- **VS Code** — MCP / Copilot MCP server config (client-specific location)
- **OpenCode** — MCP server entry with `command` + `args` + `env`

Match `mcpServers` key (or client name field) to `mcp.name` in `config.yaml` if you want them aligned.

### HTTP transport (URL clients)

For tools that only speak MCP over HTTP, run:

```bash
npm run rag:mcp:http
# or:
.venv/bin/python -m rag.mcp_server --transport http --host 127.0.0.1 --port 8000
```

| Transport | CLI / config | Client URL |
|-----------|--------------|------------|
| `http` (dual, recommended) | `--transport http` / `npm run rag:mcp:http` | **`http://127.0.0.1:8000/mcp`** (also serves `/sse`) |
| `streamable-http` | `--transport streamable-http` | `http://127.0.0.1:8000/mcp` |
| `sse` (legacy) | `--transport sse` | GET `http://127.0.0.1:8000/sse`, POST messages to `/messages/` |
| `stdio` | default | process stdin/stdout (Cursor etc.) |

Point modern URL clients at **`/mcp`**, not `/`, `/sse`, or bare `host:port`.
`GET http://127.0.0.1:8000/` returns a JSON map of endpoints.

Config / env (CLI flags override):

```yaml
mcp:
  transport: "http"       # stdio | streamable-http | sse | http
  host: "127.0.0.1"
  port: 8000
  stateless_http: true    # better for many URL clients
```

`RAG_MCP_TRANSPORT`, `RAG_MCP_HOST`, `RAG_MCP_PORT`, `RAG_MCP_PATH`.

With `qdrant.mode=local`, only one process may open the store — prefer
`qdrant.mode=server` if Cursor stdio MCP and HTTP MCP run at the same time.

## npm helpers (optional)

From `rag-mcp/`:

```bash
npm run rag:index
npm run rag:status
npm run rag:mcp       # stdio
npm run rag:mcp:http  # dual HTTP on :8000 (/mcp + /sse)
npm run rag:test
npm run rag:up        # optional Qdrant server via Docker Compose
npm run package       # build dist/rag-mcp.zip
```

## Index details

`index.sources`: `knowledge` | `code` | `lis` | `all` | comma-separated (e.g. `knowledge,lis`).
Effective buckets = `index.sources` ∩ `mcp.capabilities`.

Changing `embedding.model` requires a reindex. `rag:status` warns on mismatch.

Index status includes `git_sha` (workspace HEAD at index time) and
`requirement_id_patterns`. Compare `git_sha` with your working tree before review.

If Ollama returns `input length exceeds the context length`, lower `index.chunk_size`
and/or `embedding.max_input_chars`, then reindex.

Speed up indexing with parallel embedding requests:

```yaml
embedding:
  concurrency: 8   # try 4–16; local models may saturate earlier
```

### Requirement IDs

At index time, chunks are scanned for IDs matching `index.requirement_id_patterns`
(default `REQ-\d+`, `KR-\d+`, `US-\d+`). Mark requirements in docs (and ideally in
code comments) so `trace_requirement` can link them after reindex.

Useful knowledge to keep under existing globs:

- Requirements with stable IDs (`docs/requirements/**/*.md`)
- ADRs / architecture decisions (`.devdoc/**/ADR*.md`)
- Review checklists / Definition of Done
- Security and operations constraints

### Qdrant lock (`already accessed` / local mode)

`qdrant.mode=local` allows **only one process** to open `qdrant_data/`.
If an MCP client is running while you `index`, you get a lock error.

Workflow with local mode:

1. Disable/stop MCP (or finish indexing first)
2. Run `index`
3. Enable MCP again

### Team / concurrent agents

Prefer **server mode** when several agents or MCP sessions share the index:

```yaml
qdrant:
  mode: "server"
  url: "http://localhost:6333"
```

```bash
npm run rag:up
```

Ownership model:

- One CI job or person runs `rag:index` (or `index --files` for small updates)
- Agents use MCP **read-only** (search / trace / impact); they do not reindex
- Call `index_status` and compare `git_sha` before relying on results in review

### Capabilities and LIS

`mcp.capabilities` turns surfaces on/off (tools + index buckets):

```yaml
mcp:
  capabilities:
    knowledge: true   # workspace docs → search_knowledge
    code: true        # source/tests → search_code
    lis: false        # org ledningssystem → search_lis
```

When `lis: true`, set `index.lis` to a markdown mirror (absolute paths OK), e.g.
synced LIS docs with YAML frontmatter (`doc_type`, `process_area`, `domain`, `status`).
Chunks are stored as `type=lis` and kept separate from workspace `documentation`.

### Tools

Tools are registered only when the matching capability is on
(`index_status` / `list_sources` always).

| Tool | Purpose |
|------|---------|
| `index_status` | Freshness, model, `git_sha`, stale hints |
| `list_sources` | Capabilities, apps, globs (incl. LIS), patterns |
| `search_knowledge` | Workspace docs (`type=documentation`); optional `path_prefix` |
| `search_code` | Code/tests; optional `app`, `path_prefix` |
| `search_lis` | LIS / ledningssystem; optional `doc_type`, `process_area`, `domain`, `status` |
| `get_context_pack` | Structured pack from enabled sources (docs / code / LIS) |
| `trace_requirement` | Requirement ID/text → docs + code/tests |
| `impact_of_change` | Likely code, docs, tests, risks for a change |
| `find_gaps` | Heuristic docs↔code coverage gaps |

### Resources

| URI | Content |
|-----|---------|
| `rag://status` | Same JSON as `index_status` |
| `rag://sources` | Same JSON as `list_sources` |

### Prompts

Registered when `knowledge` or `code` is enabled.

| Prompt | Use |
|--------|-----|
| `change-plan` | Plan a change with mandatory tool sequence |
| `pr-review` | Review against requirements/docs |
| `requirement-coverage` | Coverage for one requirement |
| `onboarding-slice` | Short reading guide |
| `regression-check` | Likely regressions for a changed area |

## Debug search

```bash
.venv/bin/python -m rag.cli search "architecture overview" --mode knowledge
.venv/bin/python -m rag.cli search "BookingService" --mode code --app web
.venv/bin/python -m rag.cli search "booking" --mode code --path-prefix apps/web/
.venv/bin/python -m rag.cli search "change management" --mode lis --process-area utveckla
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

## Packaging this repo

```bash
bash scripts/package.sh
# → dist/rag-mcp.zip
```

The zip excludes `.venv/`, `qdrant_data/`, `config.yaml`, `index_status.json`, and caches.

## Layout

See `rag/` for config, embeddings client, Qdrant store, indexer, retrieval, and MCP server.
Architecture notes: [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md).
