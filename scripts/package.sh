#!/usr/bin/env bash
# Build a distributable zip of rag-mcp (no venv, index data, or local config).
# Optional VERSION env (e.g. v0.1.0) → dist/rag-mcp-${VERSION}.zip; else rag-mcp.zip.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
STAGE="$DIST/rag-mcp"
VERSION="${VERSION:-}"
if [[ -n "$VERSION" ]]; then
  ZIP_NAME="rag-mcp-${VERSION}.zip"
else
  ZIP_NAME="rag-mcp.zip"
fi
ZIP="$DIST/$ZIP_NAME"

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
  LICENSE
  CONTRIBUTING.md
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
  rm -f "$ZIP_NAME"
  zip -qr "$ZIP_NAME" rag-mcp
)

rm -rf "$STAGE"
echo "Wrote $ZIP"
