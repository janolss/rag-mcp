from rag.indexer.frontmatter import lis_fields_from_frontmatter, split_frontmatter


def test_split_frontmatter_extracts_yaml_and_body():
    text = """---
id: doc-1
doc_type: anvisning
process_area: utveckla
domain: utveckla
status: approved
title: Example
---
# Body

Hello.
"""
    meta, body = split_frontmatter(text)
    assert meta["id"] == "doc-1"
    assert meta["doc_type"] == "anvisning"
    assert body.lstrip().startswith("# Body")


def test_split_frontmatter_absent():
    meta, body = split_frontmatter("# Just markdown\n")
    assert meta == {}
    assert body.startswith("# Just")


def test_lis_fields_map_id_to_document_id():
    fields = lis_fields_from_frontmatter(
        {
            "id": "utveckla-anvisning-x",
            "doc_type": "anvisning",
            "process_area": "utveckla",
            "domain": "utveckla",
            "status": "approved",
            "title": "Anvisning X",
            "headings": ["ignored"],
        }
    )
    assert fields == {
        "document_id": "utveckla-anvisning-x",
        "doc_type": "anvisning",
        "process_area": "utveckla",
        "domain": "utveckla",
        "status": "approved",
        "title": "Anvisning X",
    }
