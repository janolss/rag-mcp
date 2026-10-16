"""Code chunking: language adapters with size-based fallback."""

from __future__ import annotations

from typing import Any

from rag.indexer.split import enforce_max_len, hard_split_text


def chunk_code_size(
    text: str,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """Split source text into overlapping windows preferring blank-line boundaries."""
    content = text.strip()
    if not content:
        return []

    if len(content) <= chunk_size:
        return [{"content": content, "section": None, "chunk_key": "size:0"}]

    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content]

    chunks: list[dict[str, Any]] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current.strip():
                chunks.append({"content": current.strip(), "section": None})
                current = ""
            for piece in hard_split_text(para, chunk_size=chunk_size, overlap=chunk_overlap):
                chunks.append({"content": piece, "section": None})
            continue

        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > chunk_size and current:
            chunks.append({"content": current.strip(), "section": None})
            tail = current[-chunk_overlap:] if chunk_overlap > 0 else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
            if len(current) > chunk_size:
                for piece in hard_split_text(current, chunk_size=chunk_size, overlap=chunk_overlap):
                    chunks.append({"content": piece, "section": None})
                current = ""
        else:
            current = candidate

    if current.strip():
        chunks.append({"content": current.strip(), "section": None})

    result = enforce_max_len(chunks, chunk_size=chunk_size, overlap=chunk_overlap)
    for index, chunk in enumerate(result):
        chunk.setdefault("chunk_key", f"size:{index}")
    return result


def chunk_code(
    text: str,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Public entry: structural language chunking when possible, else size windows."""
    from rag.indexer.languages import chunk_source

    return chunk_source(
        text,
        language=language,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
