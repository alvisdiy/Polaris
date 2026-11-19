"""The guard that decides what re-extraction may propose.

Re-running the extractor over approved records surfaced three ways the
operation could quietly damage published data. Each has a test here, because
the guard is the only thing standing between an extractor change and 40
human-reviewed records.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from services.ingestion.real_extractor import DeterministicLLMClient

pytestmark = pytest.mark.unit

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "v013_reextract_funding_candidates.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("v013_reextract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the guard -------------------------------------------------------------


def test_a_classification_the_evidence_does_not_state_is_blocked():
    """A benefits table with no mention of travel is not evidence of travel funding."""
    module = _load()
    evidence = {"statement": "Scholarship | ¥143,000 per month | ¥117,000 per month"}
    assert module._is_supported("Travel Support", evidence) is False


def test_a_classification_the_evidence_states_is_allowed():
    module = _load()
    evidence = {"statement": "Covers full tuition, a monthly stipend and airfare."}
    assert module._is_supported("Fully Funded", evidence) is True


def test_proposing_an_empty_value_is_never_allowed():
    """Clearing a human-approved value on an extractor's say-so is a downgrade."""
    module = _load()
    assert module._is_supported(None, {"statement": "Fully funded."}) is False


def test_a_classification_without_evidence_is_never_allowed():
    module = _load()
    assert module._is_supported("Fully Funded", None) is False
    assert module._is_supported("Fully Funded", {"statement": ""}) is False


def test_an_unknown_classification_is_blocked_rather_than_assumed_safe():
    """The guard fails closed for a value it has no terms for."""
    module = _load()
    assert module._is_supported("Something Invented", {"statement": "anything at all"}) is False


# --- the traps this guard exists for --------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Applicants must be enrolled in a full-time MSc programme.",
        "Full-time PhD students may apply.",
        "This is a full time course.",
    ],
)
def test_full_time_never_becomes_fully_funded(text):
    """"full-time" describes the course, not the funding."""
    result = DeterministicLLMClient().extract_scholarship(
        clean_text=text, source_url="https://example.org/s", default_country="GB"
    )
    assert result["funding_type"] != "Fully Funded"
    assert result["funding_type"] is None


def test_a_waiver_is_not_collapsed_into_tuition_only():
    result = DeterministicLLMClient().extract_scholarship(
        clean_text="Applicants receive a full tuition waiver for the programme.",
        source_url="https://example.org/s",
        default_country="GB",
    )
    assert result["funding_type"] == "Tuition Waiver"


def test_every_classified_value_carries_its_evidence():
    """A classification with no cited sentence is not explainable."""
    for text in [
        "The award is fully funded and covers full tuition and a monthly stipend.",
        "A monthly living allowance of £1,452 is provided to each student.",
        "Round-trip travel costs are covered by the scheme.",
    ]:
        result = DeterministicLLMClient().extract_scholarship(
            clean_text=text, source_url="https://example.org/s", default_country="GB"
        )
        if result["funding_type"] is not None:
            evidence = result["_extraction"]["funding_evidence"]
            assert evidence is not None
            assert evidence["statement"]


def test_no_classification_means_no_evidence():
    result = DeterministicLLMClient().extract_scholarship(
        clean_text="Scholarship available for eligible international students.",
        source_url="https://example.org/s",
        default_country="GB",
    )
    assert result["funding_type"] is None
    assert result["_extraction"]["funding_evidence"] is None
