"""Integration tests for FrontierRepository (DB-backed, rollback-isolated)."""

from datetime import datetime, timedelta, timezone

import pytest

from database.models.country import Country
from database.models.discovery_frontier import FrontierState
from services.exploration.repositories.frontier_repository import (
    FrontierBounds,
    FrontierObservation,
    FrontierRepository,
)


@pytest.fixture
def session(exploration_session):
    """Rollback-only session: the shared database stays untouched."""
    return exploration_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def repo(session):
    return FrontierRepository(session, FrontierBounds(max_pages_per_domain=3, max_depth=2))


class TestUpsertMerge:
    def test_insert_new_candidate(self, repo, jp_country):
        candidate, created = repo.upsert_candidate(
            jp_country.country_id,
            "https://example.com/scholarships",
            origin="web_search",
            observation=FrontierObservation(origin="web_search", origin_query="q1", rank=1),
        )
        assert created
        assert candidate.state == FrontierState.PENDING
        assert candidate.evidence["observations"][0]["origin_query"] == "q1"

    def test_rediscovery_merges_evidence_not_duplicate(self, repo, jp_country):
        """CRITICAL: same URL via 3 different queries keeps all observations."""
        url = "https://merge-test.example.com/page"
        for i in range(3):
            repo.upsert_candidate(
                jp_country.country_id,
                url,
                origin="web_search",
                observation=FrontierObservation(
                    origin="web_search", origin_query=f"query-{i}", rank=i + 1
                ),
            )
        candidate = repo._existing_or_none(
            jp_country.country_id,
            __import__("services.exploration.url_utils", fromlist=["url_hash"]).url_hash(url),
        )
        observations = candidate.evidence["observations"]
        assert len(observations) == 3
        assert {o["origin_query"] for o in observations} == {"query-0", "query-1", "query-2"}

    def test_merge_across_origins(self, repo, jp_country):
        url = "https://multi-origin.example.com/page"
        repo.upsert_candidate(
            jp_country.country_id, url, origin="web_search",
            observation=FrontierObservation(origin="web_search", origin_query="search q"),
        )
        repo.upsert_candidate(
            jp_country.country_id, url, origin="link_expansion",
            observation=FrontierObservation(origin="link_expansion", anchor_text="official link"),
        )
        candidate = repo._existing_or_none(
            jp_country.country_id,
            __import__("services.exploration.url_utils", fromlist=["url_hash"]).url_hash(url),
        )
        origins = {o["origin"] for o in candidate.evidence["observations"]}
        assert origins == {"web_search", "link_expansion"}

    def test_priority_takes_best(self, repo, jp_country):
        url = "https://priority.example.com/page"
        repo.upsert_candidate(jp_country.country_id, url, origin="web_search", priority=5)
        candidate, _ = repo.upsert_candidate(jp_country.country_id, url, origin="seed", priority=1)
        assert candidate.priority == 1

    def test_rejected_candidate_stays_terminal(self, repo, jp_country):
        """A verdict-backed rejection is not resurrected by new evidence."""
        url = "https://rejected-stays.example.com/jobs"
        repo.upsert_candidate(jp_country.country_id, url, origin="web_search", priority=2)
        candidate = repo.claim_next(jp_country.country_id)
        repo.mark_rejected(candidate, {"reason": "employment page"})

        merged, created = repo.upsert_candidate(
            jp_country.country_id, url, origin="seed", priority=1
        )
        assert not created
        assert merged.state == FrontierState.REJECTED
        assert merged.priority == 1  # best priority still recorded

    def test_consumed_candidate_requeued_on_better_priority(self, repo, jp_country):
        """DONE candidates come back when strictly better evidence arrives."""
        url = "https://requeue.example.com/page"
        repo.upsert_candidate(jp_country.country_id, url, origin="web_search", priority=5)
        candidate = repo.claim_next(jp_country.country_id)
        repo.mark_done(candidate, {"reason": "processed"})

        same, _ = repo.upsert_candidate(
            jp_country.country_id, url, origin="web_search", priority=5
        )
        assert same.state == FrontierState.DONE, "equal priority must not requeue"

        better, _ = repo.upsert_candidate(
            jp_country.country_id, url, origin="seed", priority=1
        )
        assert better.state == FrontierState.PENDING
        assert better.priority == 1

    def test_url_normalization_dedup(self, repo, jp_country):
        a, created_a = repo.upsert_candidate(
            jp_country.country_id, "https://www.example.com/page?utm_source=x", origin="seed"
        )
        b, created_b = repo.upsert_candidate(
            jp_country.country_id, "https://example.com/page", origin="seed"
        )
        assert created_a
        assert not created_b
        assert a.candidate_id == b.candidate_id


class TestBounds:
    def test_max_depth_enforced(self, session, jp_country):
        repo = FrontierRepository(session, FrontierBounds(max_depth=2))
        candidate, created = repo.upsert_candidate(
            jp_country.country_id, "https://deep.example.com/page", origin="link_expansion", depth=3
        )
        assert not created

    def test_per_domain_cap_counts_fetched_pages(self, session, jp_country):
        """The domain budget is spent by fetching, not by queuing.

        It used to be incremented in upsert_candidate *and* in the engine's
        fetch path, so a budget of N pages was exhausted after roughly N/2
        reads — and the rejected half was never fetched at all.
        """
        repo = FrontierRepository(session, FrontierBounds(max_pages_per_domain=2))
        for i in range(3):
            repo.upsert_candidate(
                jp_country.country_id, f"https://capped.example.com/p{i}", origin="seed"
            )
        assert repo.admitted == 3, "queuing URLs must not consume the page budget"
        assert repo.rejected_by_bounds == 0

        # Two pages were actually read from this domain.
        repo.bounds.processed_domains["capped.example.com"] = 2
        _, created = repo.upsert_candidate(
            jp_country.country_id, "https://capped.example.com/p4", origin="link_expansion"
        )
        assert not created
        assert repo.rejected_by_bounds == 1

    def test_max_candidates_enforced(self, session, jp_country):
        """The advertised per-run candidate cap is actually read.

        `FrontierBounds.max_candidates` was declared and never used, so a run
        could admit without limit while its config claimed a bound.
        """
        repo = FrontierRepository(session, FrontierBounds(max_candidates=2))
        for i in range(3):
            repo.upsert_candidate(
                jp_country.country_id, f"https://maxcand.example.com/p{i}", origin="seed"
            )
        assert repo.admitted == 2
        assert repo.rejected_by_bounds == 1

    def test_aggregator_urls_are_not_admitted(self, repo, jp_country):
        """A listing site is not a candidate, whichever path found it.

        The search surface filtered them, but link expansion did not: 32
        globaladmissions.com URLs entered a live run and spent fetch budget.
        """
        candidate, created = repo.upsert_candidate(
            jp_country.country_id,
            "https://www.globaladmissions.com/scholarships/japan/master",
            origin="link_expansion",
        )
        assert not created
        assert candidate is None
        assert repo.skipped_aggregators == 1

    def test_social_urls_are_not_admitted(self, repo, jp_country):
        candidate, created = repo.upsert_candidate(
            jp_country.country_id,
            "https://www.youtube.com/watch?v=abc",
            origin="link_expansion",
        )
        assert not created
        assert candidate is None
        assert repo.skipped_aggregators == 1


class TestClaimAndLease:
    def test_claim_returns_pending_and_marks_in_progress(self, repo, jp_country):
        repo.upsert_candidate(jp_country.country_id, "https://claim.example.com/a", origin="seed", priority=0)
        claimed = repo.claim_next(jp_country.country_id)
        assert claimed is not None
        assert claimed.url.endswith("/a"), "hermetic claim required"
        assert claimed.state == FrontierState.IN_PROGRESS

    def test_claimed_not_reclaimed(self, repo, jp_country):
        repo.upsert_candidate(jp_country.country_id, "https://lease.example.com/a", origin="seed", priority=0)
        first = repo.claim_next(jp_country.country_id)
        assert first.url.endswith("/a"), "hermetic claim required"
        second = repo.claim_next(jp_country.country_id)
        if second is not None:
            assert second.candidate_id != first.candidate_id

    def test_stale_lease_recovered(self, repo, jp_country, session):
        """CRITICAL: expired leases are reclaimed (stale-task recovery)."""
        repo.upsert_candidate(jp_country.country_id, "https://stale.example.com/a", origin="seed", priority=0)
        claimed = repo.claim_next(jp_country.country_id)
        assert claimed.url.endswith("/a"), "hermetic claim required"
        # Simulate a crashed worker: lease expired in the past. Flush (not
        # commit) so claim_next's raw recovery UPDATE sees it, while the test
        # stays inside the rollback-only transaction.
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.flush()

        recovered = repo.claim_next(jp_country.country_id)
        assert recovered is not None
        assert recovered.candidate_id == claimed.candidate_id
        assert recovered.state == FrontierState.IN_PROGRESS

    def test_claim_empty_frontier_returns_none(self, repo, jp_country):
        assert repo.count_pending(jp_country.country_id) == 0
        assert repo.claim_next(jp_country.country_id) is None


class TestRetries:
    def test_transient_failure_schedules_retry(self, repo, jp_country, session):
        repo.upsert_candidate(jp_country.country_id, "https://retry.example.com/a", origin="seed", priority=0)
        candidate = repo.claim_next(jp_country.country_id)
        assert candidate.url.endswith("/a"), "hermetic claim required"
        will_retry = repo.mark_failed_transient(candidate, "timeout", max_retries=3)
        assert will_retry
        assert candidate.state == FrontierState.PENDING
        assert candidate.retry_count == 1
        assert candidate.next_retry_at > datetime.now(timezone.utc)

    def test_retries_exhausted_marks_failed(self, repo, jp_country, session):
        repo.upsert_candidate(jp_country.country_id, "https://exhaust.example.com/a", origin="seed", priority=0)
        candidate = repo.claim_next(jp_country.country_id)
        assert candidate.url.endswith("/a"), "hermetic claim required"
        candidate.retry_count = 2  # one prior failure
        will_retry = repo.mark_failed_transient(candidate, "timeout", max_retries=3)
        assert not will_retry
        assert candidate.state == FrontierState.FAILED


class TestTerminalStates:
    def test_mark_rejected_preserves_evidence(self, repo, jp_country):
        url = "https://reject.example.com/jobs"
        repo.upsert_candidate(
            jp_country.country_id,
            url,
            origin="web_search",
            priority=0,  # claim first
            observation=FrontierObservation(origin="web_search", origin_query="jobs q"),
        )
        candidate = repo.claim_next(jp_country.country_id)
        assert candidate.url.endswith("/jobs"), "hermetic claim required"
        repo.mark_rejected(candidate, {"classification": {"label": "JOB"}, "reason": "employment"})
        assert candidate.state == FrontierState.REJECTED
        assert candidate.outcome["reason"] == "employment"
        assert candidate.evidence["observations"]  # provenance retained
