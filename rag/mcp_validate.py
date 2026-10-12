"""Parameter checks for MCP tool arguments."""

from __future__ import annotations

TOP_K_MIN = 1
TOP_K_MAX = 50

LIS_DOC_TYPES = frozenset(
    {
        "policy",
        "riktlinje",
        "anvisning",
        "instruktion",
        "mall",
        "vagledning",
        "vägledning",
        "checklista",
    }
)

LIS_PROCESS_AREAS = frozenset(
    {
        "ledning",
        "behov",
        "planera",
        "utveckla",
        "leverera",
        "stod",
        "stöd",
    }
)

LIS_STATUSES = frozenset({"approved", "draft"})


def require_nonempty(name: str, value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return f"Error: {name} cannot be empty."
    return None


def validate_top_k(value: int | None, *, name: str = "top_k") -> str | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        return f"Error: {name} must be an integer between {TOP_K_MIN} and {TOP_K_MAX}."
    if value < TOP_K_MIN or value > TOP_K_MAX:
        return f"Error: {name} must be between {TOP_K_MIN} and {TOP_K_MAX} (got {value})."
    return None


def _optional_lower(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text.lower() if text else None


def validate_lis_filters(
    *,
    doc_type: str | None = None,
    process_area: str | None = None,
    status: str | None = None,
) -> str | None:
    dt = _optional_lower(doc_type)
    if dt is not None and dt not in LIS_DOC_TYPES:
        return (
            f"Error: doc_type must be one of {sorted(LIS_DOC_TYPES)} (got {doc_type!r})."
        )

    pa = _optional_lower(process_area)
    if pa is not None and pa not in LIS_PROCESS_AREAS:
        return (
            "Error: process_area must be one of "
            f"{sorted(LIS_PROCESS_AREAS)} (got {process_area!r})."
        )

    st = _optional_lower(status)
    if st is not None and st not in LIS_STATUSES:
        return (
            f"Error: status must be one of {sorted(LIS_STATUSES)} (got {status!r})."
        )

    return None
