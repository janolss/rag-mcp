"""Reciprocal Rank Fusion for hybrid retrieval."""

from __future__ import annotations

from typing import Any, Protocol


class RankedItem(Protocol):
    @property
    def id(self) -> str: ...


def reciprocal_rank_fusion(
    ranked_lists: list[list[Any]],
    *,
    id_fn: Any = None,
    k: int = 60,
    limit: int | None = None,
) -> list[tuple[str, float, Any]]:
    """
    Fuse independent ranked lists with RRF.

    Returns ``(id, score, exemplar_item)`` sorted by descending score.
    """
    get_id = id_fn or (lambda item: getattr(item, "id", None) or getattr(item, "point_id", None))
    scores: dict[str, float] = {}
    exemplars: dict[str, Any] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            item_id = str(get_id(item))
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            exemplars.setdefault(item_id, item)
    fused = sorted(
        ((item_id, score, exemplars[item_id]) for item_id, score in scores.items()),
        key=lambda row: row[1],
        reverse=True,
    )
    if limit is not None:
        return fused[:limit]
    return fused
