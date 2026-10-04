from rag.indexer.chunk_code import chunk_code


def test_small_file_single_chunk():
    chunks = chunk_code("export function hello() { return 1 }", chunk_size=200)
    assert len(chunks) == 1
    assert chunks[0]["section"] is None


def test_large_file_multiple_chunks():
    text = "\n\n".join([f"function f{i}() {{\n  return {i};\n}}" for i in range(30)])
    chunks = chunk_code(text, chunk_size=120, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(c["content"].strip() for c in chunks)


def test_huge_block_without_blank_lines_is_hard_split():
    # Minified / dense files have no \n\n — must still respect chunk_size
    text = "x" * 5000
    chunks = chunk_code(text, chunk_size=1000, chunk_overlap=100)
    assert len(chunks) > 1
    assert all(len(c["content"]) <= 1000 for c in chunks)
