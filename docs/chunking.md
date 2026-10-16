# Code and document chunking

Markdown keeps `chunk_markdown`. Code uses language adapters under
`rag/indexer/languages/` with a size-window fallback.

## Adapters

| Language | Parser | Notes |
|----------|--------|-------|
| Python | stdlib `ast` | Functions, methods, classes, imports |
| TypeScript / JavaScript | tree-sitter | Optional if packages missing → size fallback |
| Other / syntax errors | size windows | Never fails the whole source |

## Metadata

Structural chunks may include `symbol`, `symbol_kind`, `chunk_key`, and
`imports`. `chunk_key` is stable across irrelevant whitespace for Python.

## Dependencies

```bash
pip install '.[parsers]'
# or from requirements.txt: tree-sitter, tree-sitter-javascript, tree-sitter-typescript
```
