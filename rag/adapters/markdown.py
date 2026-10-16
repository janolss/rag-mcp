"""Markdown filesystem adapter."""

from __future__ import annotations

from pathlib import Path

from rag.adapters.base import AdapterError, ExtractedDocument
from rag.indexer.walk import read_text_file


class MarkdownAdapter:
    name = "markdown"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".markdown"}

    def extract(self, path: Path, *, document_id: str) -> ExtractedDocument:
        try:
            content = read_text_file(path)
        except OSError as exc:
            raise AdapterError(f"markdown adapter failed for {path.name}: {exc}") from exc
        return ExtractedDocument(
            document_id=document_id,
            path=document_id,
            content=content,
            media_type="text/markdown",
            language="markdown",
            metadata={"format": "markdown"},
            adapter=self.name,
        )
