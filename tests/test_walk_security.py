"""Walk-time security filtering."""

from __future__ import annotations

from pathlib import Path

from rag.indexer.sources import SourceSpec
from rag.indexer.walk import walk_files
from rag.security.paths import PathSecurityPolicy


def test_walk_skips_secrets_and_outside_files(tmp_path: Path):
    root = tmp_path / "repo"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "ok.md").write_text("# ok", encoding="utf-8")
    (docs / ".env").write_text("X=1", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# outside", encoding="utf-8")

    files = walk_files(
        root,
        (SourceSpec("docs/**/*.md", "knowledge"),),
        policy=PathSecurityPolicy(),
    )
    names = [path.name for path, _bucket in files]
    assert names == ["ok.md"]


def test_walk_allows_registered_external_lis_root(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    lis = tmp_path / "lis-docs"
    lis.mkdir()
    (lis / "a.md").write_text("# a", encoding="utf-8")
    pattern = str(lis / "**" / "*.md")
    files = walk_files(
        root,
        (SourceSpec(pattern, "lis"),),
        policy=PathSecurityPolicy(),
        extra_roots=[lis],
    )
    assert len(files) == 1
    assert files[0][1] == "lis"
