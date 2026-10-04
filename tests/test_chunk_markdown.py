from rag.indexer.chunk_markdown import chunk_markdown


def test_chunk_markdown_keeps_section_titles():
    text = """# Overview

Intro paragraph.

## Multi-tenancy

Tenant isolation details that are long enough to stay in one chunk.

### Database access

How MySQL is selected per tenant.
"""
    chunks = chunk_markdown(text, chunk_size=500, chunk_overlap=40)
    sections = {c["section"] for c in chunks}
    assert "Overview" in sections
    assert "Multi-tenancy" in sections
    assert "Database access" in sections


def test_chunk_markdown_splits_large_section():
    body = "\n\n".join([f"Paragraph {i} " + ("word " * 40) for i in range(12)])
    text = f"## Big section\n\n{body}"
    chunks = chunk_markdown(text, chunk_size=200, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(c["section"] == "Big section" for c in chunks)
