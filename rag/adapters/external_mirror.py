"""External mirror adapter: reads only from an already-synced local mirror root."""

from __future__ import annotations

from pathlib import Path

from rag.adapters.base import AdapterError, ExtractedDocument
from rag.adapters.filesystem import FilesystemTextAdapter
from rag.adapters.markdown import MarkdownAdapter


class ExternalMirrorAdapter:
    """
    Treat an external system sync directory as a normal filesystem source.

    External APIs are never called here; operators sync into a registered root.
    """

    name = "external_mirror"

    def supports(self, path: Path) -> bool:
        return MarkdownAdapter().supports(path) or FilesystemTextAdapter().supports(path)

    def extract(self, path: Path, *, document_id: str) -> ExtractedDocument:
        try:
            if MarkdownAdapter().supports(path):
                doc = MarkdownAdapter().extract(path, document_id=document_id)
            else:
                doc = FilesystemTextAdapter().extract(path, document_id=document_id)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"external_mirror adapter failed for {path.name}: {exc}") from exc
        return ExtractedDocument(
            document_id=doc.document_id,
            path=doc.path,
            content=doc.content,
            media_type=doc.media_type,
            language=doc.language,
            metadata={**doc.metadata, "mirror": "true"},
            adapter=self.name,
        )
