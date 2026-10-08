"""Derive chunk metadata from repository-relative paths."""

from __future__ import annotations

from pathlib import Path

from rag.config import IndexConfig

LANGUAGE_BY_SUFFIX = {
    ".ts": "typescript",
    ".js": "javascript",
    ".ejs": "ejs",
    ".md": "markdown",
    ".py": "python",
    ".tsx": "typescript",
    ".jsx": "javascript",
}


def metadata_from_path(
    rel_path: str,
    index: IndexConfig | None = None,
    *,
    bucket: str | None = None,
) -> dict[str, str | None]:
    """
    Map a path identity to type/app/language metadata.

    Documentation: README / paths under configured documentation_prefixes.
    LIS: bucket=\"lis\" → type=lis (organizational governance docs).
    App label: first matching apps[].prefix (longest match wins).
    Tests: any path segment named tests/test → type=test when under an app.
    """
    cfg = index or IndexConfig()
    normalized = rel_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = Path(normalized)
    suffix = path.suffix.lower()
    language = LANGUAGE_BY_SUFFIX.get(suffix)

    if bucket == "lis":
        return {
            "type": "lis",
            "app": "global",
            "language": language or "markdown",
            "file": normalized,
        }

    parts = path.parts
    under_tests = "tests" in parts or "test" in parts

    if _is_documentation(normalized, cfg):
        return {
            "type": "documentation",
            "app": "global",
            "language": language or "markdown",
            "file": normalized,
        }

    app = _match_app(normalized, cfg)
    if app is not None:
        return {
            "type": "test" if under_tests else "code",
            "app": app,
            "language": language,
            "file": normalized,
        }

    return {
        "type": "test" if under_tests else "code",
        "app": "global",
        "language": language,
        "file": normalized,
    }


def _is_documentation(normalized: str, cfg: IndexConfig) -> bool:
    if Path(normalized).name.lower() == "readme.md":
        return True
    prefixes: list[str] = []
    for raw in cfg.documentation_prefixes:
        prefix = raw.replace("\\", "/")
        if not prefix.endswith("/"):
            prefix = f"{prefix}/"
        prefixes.append(prefix)
    return normalized.startswith(tuple(prefixes))


def _match_app(normalized: str, cfg: IndexConfig) -> str | None:
    # Prefer longest prefix so apps/web/api/ beats apps/
    rules = sorted(cfg.apps, key=lambda r: len(r.prefix), reverse=True)
    for rule in rules:
        prefix = rule.prefix.replace("\\", "/")
        if normalized.startswith(prefix):
            return rule.name
    return None
