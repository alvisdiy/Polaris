"""Phase 9 regression: the frontier records what the page actually looked like.

``evidence.page_signals`` was designed for exactly this and had no writer. The
tests below pin the two behaviours that make it worth having:

1. acquisition writes the signals onto the candidate it processed, so a
   rejected page can be re-examined without re-fetching it;
2. the write is telemetry, not a gate — a URL with no frontier row, or a
   repository that raises, must not take down a fetch that otherwise
   succeeded.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.discovery_frontier import (
    CandidateOrigin,
    CandidateType,
    FrontierState,
)
from services.exploration.repositories.frontier_repository import FrontierRepository

SIGNALS = {
    "intent": "SCHOLARSHIP_INDEX",
    "confidence": 0.8,
    "page_title": "Postgraduate scholarships",
    "headings": 4,
    "anchors": 61,
    "text_length": 5120,
    "raw_bytes": 228_960,
    "document_id": "00000000-0000-0000-0000-000000000000",
    "evidence": ["11 scholarship links, 0 detail sections"],
}


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def country(session):
    existing = session.query(Country).filter(Country.iso2 == "JP").first()
    return existing or Country(iso2="JP", iso3="JPN", name="Japan")


@pytest.fixture
def repository(session):
    return FrontierRepository(session)


@pytest.fixture
def candidate(session, country, repository):
    url = "https://sheffield.ac.uk/international/fees-and-funding/scholarships/postgraduate"
    row, admitted = repository.upsert_candidate(
        country_id=country.country_id,
        url=url,
        candidate_type=CandidateType.OPPORTUNITY,
        origin=CandidateOrigin.LINK_EXPANSION,
        priority=3,
    )
    assert admitted
    return row


def test_signals_are_written_onto_the_candidate_evidence(
    session, repository, candidate
):
    written = repository.record_page_signals(
        candidate.country_id, candidate.url, SIGNALS
    )
    session.commit()

    assert written is True
    session.refresh(candidate)
    stored = (candidate.evidence or {}).get("page_signals")
    assert stored is not None
    assert stored["intent"] == "SCHOLARSHIP_INDEX"
    assert stored["confidence"] == 0.8
    assert stored["anchors"] == 61
    assert stored["raw_bytes"] == 228_960
    assert stored["recorded_at"]


def test_signals_survive_alongside_existing_observations(
    session, repository, candidate
):
    from services.exploration.repositories.frontier_repository import (
        FrontierObservation,
    )

    repository._merge_observation(
        candidate,
        FrontierObservation(origin=CandidateOrigin.LINK_EXPANSION, anchor_text="Postgraduate scholarships"),
    )
    repository.record_page_signals(candidate.country_id, candidate.url, SIGNALS)
    session.commit()
    session.refresh(candidate)

    evidence = candidate.evidence or {}
    assert evidence.get("observations"), "the discovery history must not be lost"
    assert evidence.get("page_signals", {}).get("intent") == "SCHOLARSHIP_INDEX"


def test_a_later_fetch_replaces_rather_than_appends_the_signals(
    session, repository, candidate
):
    """Signals describe the page as it is now; observations hold the history."""
    repository.record_page_signals(candidate.country_id, candidate.url, SIGNALS)
    repository.record_page_signals(
        candidate.country_id,
        candidate.url,
        {**SIGNALS, "intent": "SCHOLARSHIP_DETAIL", "confidence": 0.85},
    )
    session.commit()
    session.refresh(candidate)

    stored = (candidate.evidence or {}).get("page_signals")
    assert stored["intent"] == "SCHOLARSHIP_DETAIL"
    assert len(stored["evidence"]) == len(SIGNALS["evidence"])


def test_no_candidate_is_a_normal_outcome_not_an_error(
    session, repository, candidate
):
    """Acquisition also runs over URLs that were never admitted to the frontier."""
    written = repository.record_page_signals(
        candidate.country_id,
        "https://elsewhere.example.org/never-queued",
        SIGNALS,
    )
    session.commit()
    assert written is False


def test_recorded_at_is_a_real_timestamp_not_a_stub(session, repository, candidate):
    repository.record_page_signals(candidate.country_id, candidate.url, SIGNALS)
    session.commit()
    session.refresh(candidate)

    recorded = (candidate.evidence or {})["page_signals"]["recorded_at"]
    parsed = datetime.fromisoformat(recorded)
    assert parsed.tzinfo is not None
    assert (datetime.now(timezone.utc) - parsed).total_seconds() < 120


def test_the_candidate_state_is_not_changed_by_recording_signals(
    session, repository, candidate
):
    before = candidate.state
    repository.record_page_signals(candidate.country_id, candidate.url, SIGNALS)
    session.commit()
    session.refresh(candidate)

    assert candidate.state == before == FrontierState.PENDING
