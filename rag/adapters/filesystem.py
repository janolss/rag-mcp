"""Plain-text filesystem adapter (default)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rag.adapters.base import AdapterError, ExtractedDocument
from rag.indexer.walk import read_text_file


class FilesystemTextAdapter:
    name = "filesystem"
    _SUFFIXES: ClassVar[set[str]] = {
        ".txt",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".rst",
        ".ejs",
    }

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self._SUFFIXES or path.suffix == ""

    def extract(self, path: Path, *, document_id: str) -> ExtractedDocument:
        try:
            content = read_text_file(path)
        except OSError as exc:
            raise AdapterError(f"filesystem adapter failed for {path.name}: {exc}") from exc
        return ExtractedDocument(
            document_id=document_id,
            path=document_id,
            content=content,
            media_type="text/plain",
            language=_guess_language(path),
            adapter=self.name,
        )


def _guess_language(path: Path) -> str | None:
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    return mapping.get(path.suffix.lower())
