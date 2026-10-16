# Semantic, keyword, and hybrid search

| Mode | Retriever | Notes |
|------|-----------|-------|
| `semantic` | Qdrant vectors | Default |
| `keyword` | SQLite FTS5 (`lexical.sqlite3`) | Exact tokens, symbols, IDs |
| `hybrid` | Both + Reciprocal Rank Fusion | Independent candidate lists |

## RRF

`score(d) = Σ 1 / (k + rank_i(d))` with configurable `search.rrf_k` (default 60).

## Maintenance

Upsert documents into `LexicalIndex` alongside vector upserts (tests and
indexers call `upsert_documents`). Workspace filters apply to both retrievers.

## Config

```yaml
search:
  default_mode: semantic
  rrf_k: 60
```
