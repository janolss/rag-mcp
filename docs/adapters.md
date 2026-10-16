# Document adapters (Phase 19)

| Adapter | Name | Dependency |
|---------|------|------------|
| Text | `filesystem` | none |
| Markdown | `markdown` | none |
| PDF | `pdf` | optional `pypdf` (`pip install '.[formats]'`) |
| DOCX | `docx` | optional `python-docx` |
| External mirror | `external_mirror` | none (local sync root only) |

Broken adapters raise `AdapterError` for that document only; other sources continue.

All adapters return the same `ExtractedDocument` contract (`document_id`, `path`,
`content`, `media_type`, optional `language`/`metadata`).
