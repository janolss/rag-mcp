"""Filesystem ingestion security tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag.security.paths import PathSecurityPolicy, SecurePathError, assert_within_roots


def test_rejects_path_traversal(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    escape = root / ".." / "secret.txt"
    with pytest.raises(SecurePathError, match="escapes"):
        assert_within_roots(escape, [root])


def test_rejects_symlink_escape_by_default(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(outside)
    with pytest.raises(SecurePathError, match="symlink"):
        assert_within_roots(link, [root])


def test_allows_symlink_when_enabled(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "ok.txt"
    target.write_text("ok", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(target)
    policy = PathSecurityPolicy(allow_symlinks=True)
    resolved = assert_within_roots(link, [root], policy=policy)
    assert resolved == target.resolve()


def test_rejects_secrets_and_large_files(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    env = root / ".env"
    env.write_text("TOKEN=1", encoding="utf-8")
    with pytest.raises(SecurePathError, match="secret"):
        assert_within_roots(env, [root])

    big = root / "notes.md"
    big.write_bytes(b"a" * 100)
    policy = PathSecurityPolicy(max_file_bytes=10)
    with pytest.raises(SecurePathError, match="max size"):
        assert_within_roots(big, [root], policy=policy)


def test_rejects_extended_secret_names_and_suffixes(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    for name in (".npmrc", "secrets.yaml", "local.settings.json", "kubeconfig"):
        path = root / name
        path.write_text("x", encoding="utf-8")
        with pytest.raises(SecurePathError, match="secret"):
            assert_within_roots(path, [root])
    for name in ("client.ovpn", "app.keystore", "AuthKey.p8"):
        path = root / name
        path.write_text("x", encoding="utf-8")
        with pytest.raises(SecurePathError, match="secret"):
            assert_within_roots(path, [root])


def test_registered_external_root_is_allowed(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    external = tmp_path / "lis"
    external.mkdir()
    doc = external / "policy.md"
    doc.write_text("# policy", encoding="utf-8")
    resolved = assert_within_roots(doc, [workspace, external])
    assert resolved == doc.resolve()
