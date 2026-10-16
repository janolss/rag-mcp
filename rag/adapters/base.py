"""Adapter contract for extracting documents from registered sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExtractedDocument:
    """Normalized document produced by any adapter."""

    document_id: str
    path: str
    content: str
    media_type: str
    language: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    adapter: str = "filesystem"


@runtime_checkable
class DocumentAdapter(Protocol):
    """Extract text documents from a source root under path security rules."""

    name: str

    def supports(self, path: Path) -> bool:
        """Return True when this adapter can handle ``path``."""

    def extract(self, path: Path, *, document_id: str) -> ExtractedDocument:
        """
        Extract one document.

        Must not log file contents. Failures should raise AdapterError so callers
        can isolate the fault to this source/document.
        """


class AdapterError(RuntimeError):
    """Raised when an adapter fails to extract a document."""


def adapter_registry() -> dict[str, DocumentAdapter]:
    from rag.adapters.docx import DocxAdapter
    from rag.adapters.external_mirror import ExternalMirrorAdapter
    from rag.adapters.filesystem import FilesystemTextAdapter
    from rag.adapters.markdown import MarkdownAdapter
    from rag.adapters.pdf import PdfAdapter

    adapters: list[DocumentAdapter] = [
        MarkdownAdapter(),
        FilesystemTextAdapter(),
        PdfAdapter(),
        DocxAdapter(),
        ExternalMirrorAdapter(),
    ]
    return {adapter.name: adapter for adapter in adapters}


def select_adapter(path: Path, *, preferred: str | None = None) -> DocumentAdapter:
    registry = adapter_registry()
    if preferred and preferred in registry:
        adapter = registry[preferred]
        if adapter.supports(path) or preferred in {"filesystem", "external_mirror"}:
            return adapter
    for adapter in registry.values():
        if adapter.supports(path):
            return adapter
    return registry["filesystem"]
