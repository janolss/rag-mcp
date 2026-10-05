"""Attach 1-based start/end line numbers to chunks from source text."""

from __future__ import annotations

from typing import Any


def attach_line_numbers(source_text: str, chunks: list[dict[str, Any]]) -> None:
    """
    Mutate chunks with start_line / end_line by sequential substring search.

    Overlapping chunks advance the search cursor so later pieces prefer later
    occurrences in the file.
    """
    if not source_text or not chunks:
        return

    cursor = 0
    for chunk in chunks:
        content = chunk.get("content") or ""
        if not content:
            chunk["start_line"] = None
            chunk["end_line"] = None
            continue

        idx = source_text.find(content, cursor)
        if idx < 0:
            idx = source_text.find(content)
        if idx < 0:
            chunk["start_line"] = None
            chunk["end_line"] = None
            continue

        start_line = source_text.count("\n", 0, idx) + 1
        end_line = start_line + content.count("\n")
        chunk["start_line"] = start_line
        chunk["end_line"] = end_line
        # Advance past the start so overlapping windows still progress
        cursor = idx + max(1, len(content) // 4)
