"""Full-rebuild indexing pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag.config import Config
from rag.embeddings import EmbeddingClient
from rag.indexer.chunk_code import chunk_code
from rag.indexer.chunk_markdown import chunk_markdown
from rag.indexer.metadata import metadata_from_path
from rag.indexer.sources import selected_sources
from rag.indexer.walk import read_text_file, walk_files
from rag.store import VectorStore

logger = logging.getLogger(__name__)


def build_chunks(config: Config) -> list[dict[str, Any]]:
    repo_root = config.repo_root_path
    specs = selected_sources(config.index)
    files = walk_files(repo_root, specs, config.index.ignore_dirs)
    chunks: list[dict[str, Any]] = []

    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        meta = metadata_from_path(rel, config.index)
        text = read_text_file(path)
        if not text.strip():
            continue

        if meta["type"] == "documentation" or path.suffix.lower() == ".md":
            pieces = chunk_markdown(
                text,
                chunk_size=config.index.chunk_size,
                chunk_overlap=config.index.chunk_overlap,
            )
        else:
            pieces = chunk_code(
                text,
                chunk_size=config.index.chunk_size,
                chunk_overlap=config.index.chunk_overlap,
            )

        for index, piece in enumerate(pieces):
            chunks.append(
                {
                    "type": meta["type"],
                    "app": meta["app"],
                    "file": meta["file"],
                    "language": meta["language"],
                    "section": piece.get("section"),
                    "chunk_index": index,
                    "content": piece["content"],
                }
            )

    logger.info("Built %d chunks from %d files", len(chunks), len(files))
    return chunks


def run_index(config: Config) -> dict[str, Any]:
    embedder = EmbeddingClient(config.embedding)
    ok, message = embedder.health_check()
    if not ok:
        raise RuntimeError(f"Embedding endpoint unhealthy: {message}")
    logger.info("Embedding health: %s", message)

    chunks = build_chunks(config)
    if not chunks:
        raise RuntimeError("No chunks produced — check index.sources and repo_root")

    sample_vector = embedder.embed_texts([chunks[0]["content"]], for_query=False)[0]
    vector_size = len(sample_vector)

    store = VectorStore(config)
    try:
        store.recreate_collection(vector_size)

        texts = [c["content"] for c in chunks]
        logger.info(
            "Embedding %d chunks (concurrency=%d)",
            len(texts),
            max(1, int(config.embedding.concurrency or 1)),
        )
        vectors = embedder.embed_texts(texts, for_query=False)

        count = store.upsert_chunks(chunks, vectors)
    finally:
        store.close()

    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model": config.embedding.model,
        "embedding_base_url": config.embedding.base_url,
        "collection": config.qdrant.collection,
        "qdrant_mode": config.qdrant.mode,
        "sources": config.index.sources,
        "chunk_count": count,
        "vector_size": vector_size,
        "repo_root": str(config.repo_root_path),
    }
    _write_status(config.status_file_path, status)
    logger.info("Indexed %d chunks into '%s'", count, config.qdrant.collection)
    return status


def read_status(config: Config) -> dict[str, Any] | None:
    path = config.status_file_path
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def status_report(config: Config) -> dict[str, Any]:
    file_status = read_status(config)
    store = VectorStore(config)
    try:
        points = store.count()
        exists = store.collection_exists()
    finally:
        store.close()

    report: dict[str, Any] = {
        "collection_exists": exists,
        "points_count": points,
        "status_file": str(config.status_file_path),
        "configured_model": config.embedding.model,
        "index_status": file_status,
    }
    if file_status and file_status.get("model") != config.embedding.model:
        report["warning"] = (
            f"Index was built with model {file_status.get('model')!r} but config "
            f"uses {config.embedding.model!r}. Re-run index after changing models."
        )
    return report


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)
        fh.write("\n")
