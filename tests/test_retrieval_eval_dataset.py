"""Versioned retrieval eval dataset smoke test."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "retrieval_eval.json"


def test_retrieval_eval_dataset_is_versioned():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["version"] == 1
    ids = {case["id"] for case in data["cases"]}
    assert {"symbol", "filename", "requirement", "natural_language"} <= ids
    for case in data["cases"]:
        assert case["expect_mode"] in {"semantic", "keyword", "hybrid"}
