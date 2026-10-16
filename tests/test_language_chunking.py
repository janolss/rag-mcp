"""Structural code chunking tests."""

from __future__ import annotations

from rag.indexer.languages import chunk_source


def test_python_chunks_functions_and_methods():
    source = """
import os

class Greeter:
    def hello(self, name: str) -> str:
        return f"hi {name}"

def top_level(x):
    return x + 1
"""
    chunks = chunk_source(source, language="python", chunk_size=500, chunk_overlap=20)
    symbols = {c.get("symbol") for c in chunks}
    assert "Greeter" in symbols
    assert "Greeter.hello" in symbols
    assert "top_level" in symbols
    keys = {c.get("chunk_key") for c in chunks}
    assert any(k and k.startswith("function:top_level") for k in keys)


def test_python_syntax_error_falls_back():
    chunks = chunk_source("def broken(:\n", language="python", chunk_size=200, chunk_overlap=10)
    assert chunks
    assert chunks[0]["content"]


def test_typescript_function_chunks():
    source = """
import { foo } from './foo';

export function greet(name: string): string {
  return 'hi ' + name;
}

export class Service {
  run() { return 1; }
}
"""
    chunks = chunk_source(source, language="typescript", chunk_size=800, chunk_overlap=20)
    assert chunks
    kinds = {c.get("symbol_kind") for c in chunks}
    assert "function" in kinds or "class" in kinds


def test_unknown_language_uses_size_fallback():
    text = "alpha\n\n" + ("beta " * 200)
    chunks = chunk_source(text, language="ruby", chunk_size=100, chunk_overlap=10)
    assert len(chunks) >= 1
    assert all(c.get("chunk_key", "").startswith("size:") for c in chunks)


def test_structural_keys_stable_across_whitespace():
    a = "def foo():\n    return 1\n"
    b = "def foo():\n\n    return 1\n"
    ca = chunk_source(a, language="python")
    cb = chunk_source(b, language="python")
    assert {c["chunk_key"] for c in ca} == {c["chunk_key"] for c in cb}
