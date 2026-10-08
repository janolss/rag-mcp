"""YAML frontmatter helpers (LIS markdown mirrors)."""

from __future__ import annotations

from typing import Any

import yaml

# Payload keys we promote from frontmatter into Qdrant
LIS_PAYLOAD_FIELDS: tuple[str, ...] = (
    "document_id",
    "doc_type",
    "process_area",
    "domain",
    "status",
    "title",
)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Split optional YAML frontmatter from markdown body.

    Expects a leading ``---`` block. Returns ``({}, text)`` when absent/invalid.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text

    raw_yaml = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :])
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text
    return parsed, body


def lis_fields_from_frontmatter(meta: dict[str, Any]) -> dict[str, str]:
    """Map frontmatter keys to LIS payload fields (string values only)."""
    out: dict[str, str] = {}
    document_id = meta.get("id") or meta.get("document_id")
    if document_id is not None and str(document_id).strip():
        out["document_id"] = str(document_id).strip()

    for key in ("doc_type", "process_area", "domain", "status", "title"):
        value = meta.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text
    return out
