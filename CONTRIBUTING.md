# Contributing

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,parsers]"
cp config.example.yaml config.yaml
```

Optional formats (PDF/DOCX): `pip install -e ".[dev,parsers,formats]"`.

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --frozen --extra dev --extra parsers
```

CI installs from `uv.lock` via `uv sync --frozen`. Prefer uv for reproducible
local installs; `pip install -e ".[dev,parsers]"` remains supported.

If you move the repo, recreate the venv (relocated `.venv` shebangs break):

```bash
rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,parsers]"
```

## Before opening a PR

```bash
npm run rag:verify
# ruff check + ruff format --check + pytest
```

Or: `python -m rag.cli doctor --skip-network` for a local health check.

## Architecture

- **Adapters** (`rag/mcp_server.py`, `rag/http_api.py`) — transport only; call `ServiceApp`.
- **Services** (`rag/services/`) — authz, workspace resolution, orchestration.
- **Indexer / retrieval / store** — indexing and search internals.
- **Security** (`rag/security/`) — path policy, bearer auth, HTTP limits.

## Guidelines

- Keep changes focused; ask before large refactors.
- Match existing code style and patterns.
- Add or update tests when behavior changes.
- Do not commit `.venv/`, `config.yaml`, `qdrant_data/`, or secrets.
- Prefer loopback HTTP; configure `mcp.auth.tokens` for non-loopback binds.
- Path security and secret denylist apply to indexing and `get_document`.
