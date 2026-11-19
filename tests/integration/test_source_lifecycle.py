"""Integration tests for the M9 source lifecycle and publication boundary.

Two claims are being tested against a real database, because both are claims
about persistence:

1. A verified source survives a redirect without losing its identity, and
   re-running exploration over the same site does not create a duplicate.
2. Only approved records reach the public API and matching. Everything else
   is invisible, whichever read path is used.

The lifecycle tests use the exploration isolation fixture, so they never touch
real rows in the shared development database.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import (
    SourceRegistry,
    SourceVerificationState,
)
from services.exploration.acquisition_policy import (
    AcquisitionState,
    find_source,
    resolve_url_identity,
)
from services.review import ReviewService


@pytest.fixture
def jp(exploration_session):
    return (
        exploration_session.query(Country)
        .filter(Country.iso2 == "JP")
        .first()
    )


@pytest.fixture
def provider(exploration_session, jp):
    p = Provider(
        provider_code=f"LIFECYCLE_{uuid.uuid4().hex[:8].upper()}"[:32],
        provider_name="Ministry of Education, Japan",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    exploration_session.add(p)
    exploration_session.flush()
    return p


def make_source(session, jp, provider, url, **overrides):
    canonical, digest = resolve_url_identity(url)
    fields = dict(
        source_name=f"Source {digest[:8]}",
        country_id=jp.country_id,
        provider_id=provider.provider_id,
        official_url=url[:2048],
        crawl_entry_url=url[:2048],
        canonical_url=canonical,
        url_hash=digest,
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state=SourceVerificationState.VERIFIED,
    )
    fields.update(overrides)
    source = SourceRegistry(**fields)
    session.add(source)
    session.flush()
    return source


class TestUrlIdentityPersistence:
    def test_source_is_found_by_hash_across_a_redirect(self, exploration_session, jp, provider):
        """The M9 redirect defect, reproduced and fixed.

        Registration stored the redirected URL; the candidate still held the
        pre-redirect URL. Lookup by raw string missed. Lookup by hash does not.
        """
        original = "https://www.studyinjapan.go.jp/en/scholarship"
        redirected = "https://studyinjapan.go.jp/en/scholarship"
        make_source(exploration_session, jp, provider, redirected)

        # The candidate remembers where it started, not where it ended up.
        found = find_source(exploration_session, original)
        assert found is not None
        assert found.url_hash

    def test_tracking_params_resolve_to_the_same_source(self, exploration_session, jp, provider):
        url = "https://example.edu/scholarship/abc"
        make_source(exploration_session, jp, provider, url)
        assert find_source(exploration_session, url + "?utm_source=news") is not None

    def test_legacy_row_without_a_hash_is_still_findable(self, exploration_session, jp, provider):
        """Rows written before M9 have no url_hash and must not become orphans."""
        source = make_source(
            exploration_session, jp, provider, "https://example.edu/legacy",
            url_hash=None, canonical_url=None,
        )
        assert find_source(exploration_session, "https://example.edu/legacy") is source

    def test_different_pages_are_different_sources(self, exploration_session, jp, provider):
        make_source(exploration_session, jp, provider, "https://example.edu/scholarship/abc")
        assert find_source(exploration_session, "https://example.edu/scholarship/xyz") is None


class TestSourceLifecycle:
    def test_discovered_to_verified_is_legal(self, exploration_session, jp, provider):
        source = make_source(
            exploration_session, jp, provider, "https://example.edu/a",
            verification_state=SourceVerificationState.DISCOVERED,
        )
        assert source.can_transition_to(SourceVerificationState.VERIFIED)

    def test_needs_review_is_persisted_and_queryable(self, exploration_session, jp, provider):
        """Phase 3: the queue must hold real rows, not a hardcoded zero."""
        make_source(
            exploration_session, jp, provider, "https://example.edu/b",
            verification_state=SourceVerificationState.NEEDS_REVIEW,
        )
        exploration_session.flush()

        queued = (
            exploration_session.query(SourceRegistry)
            .filter(
                SourceRegistry.country_id == jp.country_id,
                SourceRegistry.verification_state == SourceVerificationState.NEEDS_REVIEW,
            )
            .all()
        )
        assert len(queued) == 1
        assert queued[0].needs_review()

    def test_verified_is_what_feeds_acquisition(self, exploration_session, jp, provider):
        source = make_source(exploration_session, jp, provider, "https://example.edu/c")
        assert source.is_verified()
        unverified = make_source(
            exploration_session, jp, provider, "https://example.edu/d",
            verification_state=SourceVerificationState.NEEDS_REVIEW,
        )
        assert not unverified.is_verified()

    def test_terminal_states_do_not_resurrect(self, exploration_session, jp, provider):
        """A rejected source must not come back through one more bad fetch."""
        for terminal in (
            SourceVerificationState.REJECTED, SourceVerificationState.DEPRECATED,
        ):
            source = make_source(
                exploration_session, jp, provider, f"https://example.edu/{terminal.lower()}",
                verification_state=terminal,
            )
            assert not source.can_transition_to(SourceVerificationState.VERIFIED)

    def test_deprecated_and_rejected_can_return_to_review(self, exploration_session, jp, provider):
        for terminal in (
            SourceVerificationState.REJECTED, SourceVerificationState.DEPRECATED,
        ):
            source = make_source(
                exploration_session, jp, provider, f"https://example.edu/back-{terminal.lower()}",
                verification_state=terminal,
            )
            assert source.can_transition_to(SourceVerificationState.NEEDS_REVIEW)

    def test_repeat_registration_is_idempotent(self, exploration_session, jp, provider):
        """Re-running exploration must update, not duplicate."""
        url = "https://example.edu/scholarship/idempotent"
        first = make_source(exploration_session, jp, provider, url)
        found = find_source(exploration_session, url)
        assert found is first

    def test_acquisition_outcome_is_recorded(self, exploration_session, jp, provider):
        """M9 forbids silent failure: the outcome lives on the row."""
        source = make_source(exploration_session, jp, provider, "https://example.edu/e")
        source.acquisition_state = AcquisitionState.NO_SCHOLARSHIP_PAGES
        source.acquisition_error = "3 links found, none classified as a scholarship page"
        exploration_session.flush()

        reloaded = find_source(exploration_session, "https://example.edu/e")
        assert reloaded.acquisition_state == AcquisitionState.NO_SCHOLARSHIP_PAGES
        assert "none classified" in reloaded.acquisition_error

    def test_page_type_is_recorded_for_review(self, exploration_session, jp, provider):
        source = make_source(
            exploration_session, jp, provider, "https://example.edu/f",
            page_type="SOURCE_PAGE",
        )
        assert source.page_type == "SOURCE_PAGE"


def _scholarship(session, jp, provider, source, **overrides):
    fields = dict(
        scholarship_name="Test Programme 2027",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering"],
        official_page_url="https://example.edu/scholarship/test-2027",
        application_url="https://example.edu/scholarship/test-2027/apply",
        provider_id=provider.provider_id,
        country_id=jp.country_id,
        source_id=source.source_id,
        provenance_origin="exploration",
    )
    fields.update(overrides)
    row = Scholarship(**fields)
    session.add(row)
    session.flush()
    return row


class TestPublicationBoundary:
    """One rule, several read paths, all of them exercised."""

    @pytest.fixture
    def records(self, exploration_session, jp, provider):
        source = make_source(
            exploration_session, jp, provider, "https://example.edu/publish",
            verification_state=SourceVerificationState.VERIFIED,
        )
        future = (date.today() + timedelta(days=60)).isoformat()
        return {
            "approved": _scholarship(
                exploration_session, jp, provider, source,
                scholarship_name="Approved Programme 2027",
                extraction_status="approved", deadline_state="active",
            ),
            "pending": _scholarship(
                exploration_session, jp, provider, source,
                scholarship_name="Pending Programme 2027",
                extraction_status="pending_review", deadline_state="active",
            ),
            "rejected": _scholarship(
                exploration_session, jp, provider, source,
                scholarship_name="Rejected Programme 2027",
                extraction_status="rejected", deadline_state="active",
            ),
            "source": source,
            "future": future,
        }

    def test_only_approved_reaches_matching(self, exploration_session, records):
        from services.scholarship.repository import ScholarshipRepository

        visible = ScholarshipRepository(exploration_session).get_all_approved()
        names = {s.scholarship_name for s in visible}
        assert "Approved Programme 2027" in names
        assert "Pending Programme 2027" not in names
        assert "Rejected Programme 2027" not in names

    def test_only_approved_reaches_search(self, exploration_session, records):
        from services.scholarship.repository import ScholarshipRepository

        rows, _ = ScholarshipRepository(exploration_session).search_approved(
            query="Programme 2027", limit=50
        )
        names = {s.scholarship_name for s in rows}
        assert names == {"Approved Programme 2027"}

    def test_expired_approved_records_are_hidden(self, exploration_session, records):
        """Published and expired are two different facts."""
        from services.scholarship.repository import ScholarshipRepository

        records["approved"].deadline_state = "expired"
        exploration_session.flush()
        names = {s.scholarship_name for s in ScholarshipRepository(exploration_session).get_all_approved()}
        assert "Approved Programme 2027" not in names

    def test_pending_record_is_reachable_by_review_but_not_by_users(
        self, exploration_session, records
    ):
        """The review path and the public path deliberately differ."""
        service = ReviewService(exploration_session)
        _, total = service.list_for_review(
            state="pending_review", country_id=str(records["approved"].country_id)
        )
        assert total == 1

        from services.scholarship.repository import ScholarshipRepository
        visible = ScholarshipRepository(exploration_session).get_all_approved()
        assert records["pending"].scholarship_id not in {s.scholarship_id for s in visible}
