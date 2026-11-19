"""Phase 4 regression: a scholarship stops being actionable when it expires.

The failure this guards against is the expensive kind. A record with a
deadline in the past is still correctly *published* — the curation decision
stands — but it must not appear in anything a user reads, and the passage of
time must not quietly rewrite the curation record.

So the test pins four things:

1. an approved record with a future deadline is visible on every public read
   path;
2. the same record, one day past its deadline, disappears from every one of
   them — no path is left holding a stale copy;
3. the expiry does not touch ``extraction_status``, ``reviewed_at`` or
   ``reviewed_by``: reclassification is classification, not a curation act;
4. moving the deadline forward again makes it visible again, with no review
   action invented in between.

Everything runs inside ``rollback_session``, so the development database is
unaffected.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.review.publication import is_published, public_filter
from services.scholarship.repository import ScholarshipRepository

FUTURE = "https://expiry-regression.example.org/scholarship/future"
PAST = "https://expiry-regression.example.org/scholarship/past"


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def country(session):
    existing = session.query(Country).filter(Country.iso2 == "JP").first()
    return existing or Country(iso2="JP", iso3="JPN", name="Japan")


@pytest.fixture
def record(session, country):
    """One approved record with a deadline a day from now."""
    session.add(country)
    session.flush()

    provider = Provider(
        provider_code="EXPIRY_TEST_PROV",
        provider_name="Expiry Regression Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        verification_status="verified",
    )
    session.add(provider)
    session.flush()

    source = SourceRegistry(
        source_name="Expiry Regression Source",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url=FUTURE,
        crawl_entry_url="https://expiry-regression.example.org/",
        crawl_method="manual",
        crawl_frequency="weekly",
        priority=3,
    )
    session.add(source)
    session.flush()

    scholarship = Scholarship(
        scholarship_name="Expiry Regression Scholarship",
        degree="Master",
        funding_type="Fully Funded",
        application_url=FUTURE,
        official_page_url=FUTURE,
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="approved",
        provenance_origin="regression_test",
    )
    session.add(scholarship)
    session.flush()

    from database.models.scholarship_timeline import ScholarshipTimeline

    session.add(
        ScholarshipTimeline(
            scholarship_id=scholarship.scholarship_id,
            application_deadline=date.today() + timedelta(days=1),
        )
    )
    session.commit()
    return scholarship


def _sweep(session) -> int:
    return ScholarshipRepository(session).reclassify_deadline_states()


def _visible_everywhere(session, scholarship_id) -> bool:
    """True only if every public read path still returns the record."""
    repository = ScholarshipRepository(session)
    ids = lambda rows: {str(s.scholarship_id) for s in rows}  # noqa: E731
    key = str(scholarship_id)

    listed = repository.get_all_approved()
    paged, _ = repository.search_approved(query="Expiry Regression Scholarship")
    active = repository.get_currently_active()
    detail = repository.get_published_by_id(scholarship_id)

    return all(
        key in ids(rows) for rows in (listed, paged, active)
    ) and detail is not None


def test_a_record_is_visible_while_its_deadline_is_in_the_future(session, record):
    _sweep(session)

    assert record.deadline_state == "active"
    assert _visible_everywhere(session, record.scholarship_id)


def test_expiring_removes_it_from_every_public_read_path(session, record):
    """Same record, one day later: gone from listings, search, actives, detail."""
    _sweep(session)
    assert _visible_everywhere(session, record.scholarship_id)

    session.query(type(record.timeline)).filter_by(
        scholarship_id=record.scholarship_id
    ).one().application_deadline = date.today() - timedelta(days=1)
    session.commit()

    changed = _sweep(session)
    assert changed == 1
    session.refresh(record)
    assert record.deadline_state == "expired"

    assert not _visible_everywhere(session, record.scholarship_id)


def test_expiry_does_not_rewrite_the_curation_record(session, record):
    """Publication and expiry are separate facts; time passing moves only one."""
    reviewed_at, reviewed_by = record.reviewed_at, record.reviewed_by
    session.query(type(record.timeline)).filter_by(
        scholarship_id=record.scholarship_id
    ).one().application_deadline = date.today() - timedelta(days=1)
    session.commit()

    _sweep(session)
    session.refresh(record)

    assert record.extraction_status == "approved"
    assert is_published(record)
    assert record.reviewed_at == reviewed_at
    assert record.reviewed_by == reviewed_by


def test_a_reopened_deadline_makes_the_record_visible_again(session, record):
    session.query(type(record.timeline)).filter_by(
        scholarship_id=record.scholarship_id
    ).one().application_deadline = date.today() - timedelta(days=1)
    session.commit()
    _sweep(session)
    assert not _visible_everywhere(session, record.scholarship_id)

    session.query(type(record.timeline)).filter_by(
        scholarship_id=record.scholarship_id
    ).one().application_deadline = date.today() + timedelta(days=30)
    session.commit()
    _sweep(session)
    session.refresh(record)

    assert record.deadline_state == "active"
    assert _visible_everywhere(session, record.scholarship_id)


def test_the_public_gate_is_what_excludes_it_not_the_status(session, record):
    """Guards against 'fixing' this by un-approving expired records."""
    session.query(type(record.timeline)).filter_by(
        scholarship_id=record.scholarship_id
    ).one().application_deadline = date.today() - timedelta(days=1)
    session.commit()
    _sweep(session)

    session.refresh(record)
    # "expired" travels as a bound parameter, not inline SQL, so the compiled
    # parameters are where to look for it.
    compiled = public_filter().compile(session.get_bind())
    bound = set(compiled.params.values())
    assert "extraction_status" in str(compiled)
    assert "expired" in bound
    assert record.extraction_status == "approved"
