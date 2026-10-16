"""TypeScript/JavaScript structural chunking via tree-sitter (optional)."""

from __future__ import annotations

from typing import Any

from rag.indexer.chunk_code import chunk_code_size
from rag.indexer.split import enforce_max_len, hard_split_text

_FUNCTION_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "class_declaration",
    "export_statement",
}


def chunk_javascript(
    text: str,
    *,
    language: str = "javascript",
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    parser = _build_parser(language)
    if parser is None:
        return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    if root.has_error and not any(c.type in _FUNCTION_TYPES for c in root.children):
        # Keep going when partial trees exist; pure errors fall back.
        return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    imports = _collect_imports(root, text)
    units: list[dict[str, Any]] = []
    for child in root.children:
        units.extend(
            _emit_node(
                child,
                text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                imports=imports,
            )
        )
    if not units:
        return chunk_code_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return enforce_max_len(units, chunk_size=chunk_size, overlap=chunk_overlap)


def _build_parser(language: str):
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return None
    try:
        if language in {"typescript", "ts"}:
            import tree_sitter_typescript as tst

            lang = Language(tst.language_typescript())
        elif language in {"tsx"}:
            import tree_sitter_typescript as tst

            lang = Language(tst.language_tsx())
        else:
            import tree_sitter_javascript as tsj

            lang = Language(tsj.language())
        parser = Parser(lang)
        return parser
    except Exception:
        return None


def _node_text(node: Any, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _collect_imports(root: Any, source: str) -> list[str]:
    names: list[str] = []
    for child in root.children:
        if child.type in {"import_statement", "export_statement"}:
            text = _node_text(child, source)
            if "from" in text:
                parts = text.split("from")
                names.append(parts[-1].strip().strip("\"';").rstrip(";"))
            elif "import" in text:
                names.append(text.strip())
    return names


def _symbol_name(node: Any, source: str) -> str:
    for child in node.children:
        if child.type in {"identifier", "property_identifier", "type_identifier"}:
            return _node_text(child, source)
    return node.type


def _emit_node(
    node: Any,
    source: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    imports: list[str],
) -> list[dict[str, Any]]:
    if node.type == "export_statement":
        units: list[dict[str, Any]] = []
        for child in node.children:
            units.extend(
                _emit_node(
                    child,
                    source,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    imports=imports,
                )
            )
        return units

    if node.type not in {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
    }:
        return []

    name = _symbol_name(node, source)
    kind = "class" if node.type == "class_declaration" else "function"
    if node.type == "method_definition":
        kind = "method"
    key = f"{kind}:{name}"
    content = _node_text(node, source).strip()
    if not content:
        return []
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
    return [
        {
            "content": piece,
            "section": name,
            "symbol": name,
            "symbol_kind": kind,
            "chunk_key": f"{key}#{index}",
            "imports": imports,
        }
        for index, piece in enumerate(
            hard_split_text(content, chunk_size=chunk_size, overlap=chunk_overlap)
        )
    ]
