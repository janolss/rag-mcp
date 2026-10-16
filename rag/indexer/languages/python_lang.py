"""Python structural chunking via the stdlib ``ast`` module."""

from __future__ import annotations

import ast
from typing import Any

from rag.indexer.chunk_code import chunk_code_size
from rag.indexer.split import enforce_max_len, hard_split_text


def chunk_python(
    text: str,
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    lines = text.splitlines(keepends=True)
    imports = _collect_imports(tree)
    units: list[dict[str, Any]] = []

    module_doc = ast.get_docstring(tree)
    if module_doc:
        units.append(
            {
                "content": module_doc.strip(),
                "section": "module:docstring",
                "symbol": "<module>",
                "symbol_kind": "module",
                "chunk_key": "module:docstring",
                "imports": imports,
            }
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.extend(
                _emit_function(
                    node,
                    lines,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    imports=imports,
                    parent=None,
                )
            )
        elif isinstance(node, ast.ClassDef):
            units.extend(
                _emit_class(
                    node,
                    lines,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    imports=imports,
                )
            )

    if not units:
        return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return enforce_max_len(units, chunk_size=chunk_size, overlap=chunk_overlap)


def _collect_imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.append(module)
    return names


def _slice_lines(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end]).strip()


def _emit_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    *,
    chunk_size: int,
    chunk_overlap: int,
    imports: list[str],
    parent: str | None,
) -> list[dict[str, Any]]:
    name = f"{parent}.{node.name}" if parent else node.name
    kind = "method" if parent else "function"
    key = f"{kind}:{name}"
    content = _slice_lines(lines, node.lineno, node.end_lineno or node.lineno)
    if len(content) <= chunk_size:
        return [
            {
                "content": content,
                "section": name,
                "symbol": name,
                "symbol_kind": kind,
                "chunk_key": key,
                "imports": imports,
            }
        ]
    pieces = hard_split_text(content, chunk_size=chunk_size, overlap=chunk_overlap)
    return [
        {
            "content": piece,
            "section": name,
            "symbol": name,
            "symbol_kind": kind,
            "chunk_key": f"{key}#{index}",
            "imports": imports,
        }
        for index, piece in enumerate(pieces)
    ]


def _emit_class(
    node: ast.ClassDef,
    lines: list[str],
    *,
    chunk_size: int,
    chunk_overlap: int,
    imports: list[str],
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    class_header_end = node.lineno
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            break
        class_header_end = child.end_lineno or child.lineno
    header = _slice_lines(lines, node.lineno, class_header_end)
    if header:
        units.append(
            {
                "content": header,
                "section": node.name,
                "symbol": node.name,
                "symbol_kind": "class",
                "chunk_key": f"class:{node.name}",
                "imports": imports,
            }
        )
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.extend(
                _emit_function(
                    child,
                    lines,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    imports=imports,
                    parent=node.name,
                )
            )
    return units
