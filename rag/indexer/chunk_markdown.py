"""Markdown chunking by headings with paragraph fallback."""

from __future__ import annotations

import re
from typing import Any

from rag.indexer.split import enforce_max_len, hard_split_text

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def chunk_markdown(
    text: str,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """
    Split markdown into overlapping chunks.

    Prefers heading boundaries (#–###). Large sections are further split on
    blank-line paragraph boundaries.
    """
    if not text.strip():
        return []

    sections = _split_by_headings(text)
    chunks: list[dict[str, Any]] = []

    for section_title, section_body in sections:
        body = section_body.strip()
        if not body:
            continue
        if len(body) <= chunk_size:
            chunks.append({"content": body, "section": section_title})
            continue
        chunks.extend(
            _split_paragraphs(
                body,
                section=section_title,
                chunk_size=chunk_size,
                overlap=chunk_overlap,
            )
        )

    return enforce_max_len(chunks, chunk_size=chunk_size, overlap=chunk_overlap)


def _split_by_headings(text: str) -> list[tuple[str | None, str]]:
    lines = text.splitlines()
    sections: list[tuple[str | None, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    if not sections:
        return [(None, text)]
    return sections


def _split_paragraphs(
    text: str,
    *,
    section: str | None,
    chunk_size: int,
    overlap: int,
) -> list[dict[str, Any]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [
            {"content": piece, "section": section}
            for piece in hard_split_text(text, chunk_size=chunk_size, overlap=overlap)
        ]

    chunks: list[dict[str, Any]] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current.strip():
                chunks.append({"content": current.strip(), "section": section})
                current = ""
            for piece in hard_split_text(para, chunk_size=chunk_size, overlap=overlap):
                chunks.append({"content": piece, "section": section})
            continue

        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > chunk_size and current:
            chunks.append({"content": current.strip(), "section": section})
            tail = current[-overlap:] if overlap > 0 and len(current) > overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
            if len(current) > chunk_size:
                for piece in hard_split_text(current, chunk_size=chunk_size, overlap=overlap):
                    chunks.append({"content": piece, "section": section})
                current = ""
        else:
            current = candidate

    if current.strip():
        chunks.append({"content": current.strip(), "section": section})
    return chunks
