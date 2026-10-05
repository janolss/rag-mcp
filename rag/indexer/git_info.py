"""Git metadata helpers for index status."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def git_head_sha(repo_root: Path) -> str:
    """Return HEAD SHA for repo_root, or empty string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git rev-parse failed: %s", exc)
        return ""

    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()
