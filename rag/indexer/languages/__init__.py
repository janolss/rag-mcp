"""Language-specific code chunkers with size-based fallback."""

from __future__ import annotations

from typing import Any

from rag.indexer.chunk_code import chunk_code_size
from rag.indexer.languages.javascript import chunk_javascript
from rag.indexer.languages.python_lang import chunk_python


def chunk_source(
    text: str,
    *,
    language: str | None,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """
    Dispatch to a language adapter; unknown/broken parsers fall back to size windows.

    Each chunk may include ``section``, ``symbol``, ``symbol_kind``, ``chunk_key``,
    and ``imports`` metadata when structural parsing succeeds.
    """
    lang = (language or "").strip().lower()
    try:
        if lang in {"python", "py"}:
            return chunk_python(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if lang in {"typescript", "tsx", "javascript", "jsx", "js", "ts"}:
            return chunk_javascript(
                text,
                language=lang,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
    except Exception:
        # Syntax errors / missing parsers must not abort the whole source.
        pass
    return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
