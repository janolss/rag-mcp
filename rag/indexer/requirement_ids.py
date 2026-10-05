"""Extract requirement IDs from chunk text using configured patterns."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Sequence


DEFAULT_REQUIREMENT_ID_PATTERNS: tuple[str, ...] = (
    r"REQ-\d+",
    r"KR-\d+",
    r"US-\d+",
)


@lru_cache(maxsize=32)
def _compiled(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


def extract_requirement_ids(
    text: str,
    patterns: Sequence[str] | None = None,
) -> list[str]:
    """Return sorted unique IDs found in text (canonical uppercase form)."""
    if not text:
        return []
    pats = tuple(patterns) if patterns else DEFAULT_REQUIREMENT_ID_PATTERNS
    found: set[str] = set()
    for regex in _compiled(pats):
        for match in regex.finditer(text):
            found.add(match.group(0).upper())
    return sorted(found)


def matches_requirement_id_pattern(
    value: str,
    patterns: Sequence[str] | None = None,
) -> bool:
    """True when the entire trimmed value is a single requirement ID."""
    candidate = (value or "").strip()
    if not candidate:
        return False
    pats = tuple(patterns) if patterns else DEFAULT_REQUIREMENT_ID_PATTERNS
    for regex in _compiled(pats):
        if regex.fullmatch(candidate):
            return True
    return False


def normalize_requirement_query(
    requirement: str,
    patterns: Sequence[str] | None = None,
) -> str:
    trimmed = (requirement or "").strip()
    if matches_requirement_id_pattern(trimmed, patterns):
        return trimmed.upper()
    return trimmed
