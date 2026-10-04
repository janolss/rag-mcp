"""Shared text splitting helpers for chunkers."""

from __future__ import annotations


def hard_split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Split text into windows of at most chunk_size characters."""
    content = text.strip()
    if not content:
        return []
    if len(content) <= chunk_size:
        return [content]

    step = max(1, chunk_size - max(0, overlap))
    pieces: list[str] = []
    start = 0
    while start < len(content):
        piece = content[start : start + chunk_size].strip()
        if piece:
            pieces.append(piece)
        if start + chunk_size >= len(content):
            break
        start += step
    return pieces


def enforce_max_len(
    chunks: list[dict],
    *,
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """Re-split any chunk whose content exceeds chunk_size."""
    out: list[dict] = []
    for chunk in chunks:
        content = chunk.get("content") or ""
        if len(content) <= chunk_size:
            out.append(chunk)
            continue
        for piece in hard_split_text(content, chunk_size=chunk_size, overlap=overlap):
            cloned = dict(chunk)
            cloned["content"] = piece
            out.append(cloned)
    return out
