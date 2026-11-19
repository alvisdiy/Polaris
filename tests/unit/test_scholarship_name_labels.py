"""The section-label gate, pinned against real catalogue strings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.ingestion.extraction_quality import name_genericities, score_candidate_name

DATASET = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "scholarship_name_labels.json").read_text(
        encoding="utf-8"
    )
)
SAMPLES = DATASET["samples"]


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["name"][:45] for s in SAMPLES])
def test_the_gate_agrees_with_the_real_label(sample):
    reasons = name_genericities(sample["name"])

    if sample["expected"] == "reject":
        assert reasons, f"accepted a {sample['why']}: {sample['name']!r}"
    else:
        assert not reasons, f"rejected a real programme ({reasons}): {sample['name']!r}"


def test_the_dataset_covers_both_sides():
    """A dataset that only contains rejections proves only half the gate."""
    expectations = {sample["expected"] for sample in SAMPLES}
    assert expectations == {"accept", "reject"}
    assert sum(1 for s in SAMPLES if s["expected"] == "accept") >= 8


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["name"][:45] for s in SAMPLES])
def test_page_context_does_not_rescue_a_bad_name(sample):
    """A title and heading are evidence, not a licence to accept a section."""
    verdict = score_candidate_name(sample["name"], in_title=True, in_heading=True)

    if sample["expected"] == "reject":
        assert not verdict.accepted, f"accepted with page context: {sample['name']!r}"
    else:
        assert verdict.accepted, f"rejected a real name: {verdict.reasons}"
