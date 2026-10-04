#!/usr/bin/env bash
# Build a distributable zip of rag-mcp (no venv, index data, or local config).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
STAGE="$DIST/rag-mcp"
ZIP="$DIST/rag-mcp.zip"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"

INCLUDE=(
  rag
  tests
  scripts
  requirements.txt
  pyproject.toml
  pytest.ini
  config.example.yaml
  run_mcp.py
  docker-compose.qdrant.yml
  README.md
  RAG_ARCHITECTURE.md
  package.json
)

for item in "${INCLUDE[@]}"; do
  if [[ -e "$ROOT/$item" ]]; then
    cp -R "$ROOT/$item" "$STAGE/$item"
  else
    echo "warning: missing $item" >&2
  fi
done

# Drop caches / local junk that may have been copied with directories
find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE" -type d -name '.pytest_cache' -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete

# Do not ship local runtime artifacts if present under staged tree
rm -rf "$STAGE/qdrant_data" "$STAGE/.venv" "$STAGE/config.yaml" "$STAGE/index_status.json" "$STAGE/.env"

(
  cd "$DIST"
  rm -f rag-mcp.zip
  zip -qr rag-mcp.zip rag-mcp
)

rm -rf "$STAGE"
echo "Wrote $ZIP"
