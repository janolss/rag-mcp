"""PDF adapter (optional dependency: pypdf)."""

from __future__ import annotations

from pathlib import Path

from rag.adapters.base import AdapterError, ExtractedDocument


class PdfAdapter:
    name = "pdf"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def extract(self, path: Path, *, document_id: str) -> ExtractedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AdapterError(
                "pdf adapter requires optional dependency pypdf (pip install '.[formats]')"
            ) from exc
        try:
            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            content = "\n".join(parts).strip()
        except Exception as exc:
            raise AdapterError(f"pdf adapter failed for {path.name}: {exc}") from exc
        return ExtractedDocument(
            document_id=document_id,
            path=document_id,
            content=content,
            media_type="application/pdf",
            language=None,
            metadata={"format": "pdf", "pages": str(len(getattr(reader, "pages", [])))},
            adapter=self.name,
        )
