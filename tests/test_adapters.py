"""Adapter contract suite (Phase 19)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.adapters import AdapterError, adapter_registry, select_adapter
from rag.adapters.markdown import MarkdownAdapter


def test_markdown_and_text_adapters(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Hi\n\nbody\n", encoding="utf-8")
    py = tmp_path / "a.py"
    py.write_text("print(1)\n", encoding="utf-8")

    md_doc = select_adapter(md).extract(md, document_id="note.md")
    assert md_doc.media_type == "text/markdown"
    assert "Hi" in md_doc.content
    assert md_doc.adapter == "markdown"

    py_doc = select_adapter(py).extract(py, document_id="a.py")
    assert py_doc.language == "python"
    assert py_doc.adapter == "filesystem"


def test_pdf_docx_optional_errors(tmp_path: Path):
    registry = adapter_registry()
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 broken")
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"not-a-docx")

    with pytest.raises(AdapterError):
        registry["pdf"].extract(pdf, document_id="x.pdf")
    with pytest.raises(AdapterError):
        registry["docx"].extract(docx, document_id="x.docx")


def test_adapter_failure_isolates_source(tmp_path: Path):
    good = tmp_path / "ok.md"
    good.write_text("ok\n", encoding="utf-8")
    # Simulate unreadable by selecting markdown adapter on missing path
    adapter = MarkdownAdapter()
    docs = []
    for path, doc_id in ((good, "ok.md"), (tmp_path / "missing.md", "missing.md")):
        try:
            docs.append(adapter.extract(path, document_id=doc_id))
        except AdapterError:
            continue
    assert len(docs) == 1
    assert docs[0].document_id == "ok.md"
