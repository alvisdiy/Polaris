"""Regression coverage for the `_frontier_loop` rollback/expired-instance defect.

A candidate whose processing raised used to take the whole run down with it.

The mechanism, as captured in the live traceback of run 89266eaa (GB):

    engine.py:383  _frontier_loop   -> await self._process_candidate(candidate, run_id)
    engine.py:508  _process_candidate -> origin_url=candidate.url
    sqlalchemy.orm.attributes       -> state._load_expired(...)
    sqlalchemy.orm.loading          -> raise ObjectDeletedError(state)

`ProviderResolver` calls `session.rollback()` to recover from a provider
UniqueViolation (provider_resolver.py). That rollback expires every loaded
attribute of the candidate instance the engine is still holding, so the next
attribute read raised. The exception then reached the `_frontier_loop` handler,
which rolled back again and handed the same dead instance to
`mark_failed_transient` — so the handler crashed while handling the crash, and
`run()` recorded the run as failed. Seven of seven live runs died this way.

The invariant these tests lock in: after the handler's `session.rollback()`, no
ORM attribute of the original candidate is read. The handler is keyed on
`candidate_id` and re-reads the row by primary key.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from database.models.country import Country
from database.models.discovery_frontier import DiscoveryFrontier, FrontierState
from services.exploration.config_loader import load_country_config
from services.exploration.engine import CountryExplorationEngine
from services.exploration.repositories.frontier_repository import (
    FrontierBounds,
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
    return FrontierRepository(session, FrontierBounds(max_depth=3))


def _add(repo, jp_country, url, priority=0):
    candidate, _ = repo.upsert_candidate(
        jp_country.country_id, url, origin="seed", priority=priority
    )
    repo.session.flush()
    return candidate


def _commit_setup(session):
    """Release the savepoint holding the fixture's cleanup and test rows.

    `_frontier_loop`'s handler calls `session.rollback()`. Under the
    `rollback_session` fixture (`join_transaction_mode="create_savepoint"`)
    that rolls back to the newest savepoint, so anything left uncommitted
    would be discarded — including the fixture's own cleanup DELETE, which
    would resurrect the real JP frontier rows and derail the test.
    """
    session.commit()


def _seed_committed_then_pending(repo, jp_country, session, survivor_url, doomed_url):
    """One candidate that survives a rollback, one that does not.

    The survivor is committed first, so the handler's rollback leaves it
    alone. The doomed candidate is added afterwards and left uncommitted —
    which is the production shape: a candidate created earlier in the same
    transaction (by `upsert_candidate` during link or authority expansion) is
    claimed while still uncommitted, so the rollback in the handler discards
    its row and leaves the instance unusable.
    """
    survivor, _ = repo.upsert_candidate(
        jp_country.country_id, survivor_url, origin="seed", priority=1
    )
    session.flush()
    session.commit()
    doomed, _ = repo.upsert_candidate(
        jp_country.country_id, doomed_url, origin="seed", priority=0
    )
    session.flush()
    return survivor, doomed


# ----------------------------------------------------------------------
# Test 1 — a candidate exception must not kill the run
# ----------------------------------------------------------------------


class TestCandidateFailureDoesNotKillRun:
    @pytest.mark.asyncio
    async def test_failing_candidate_does_not_abort_the_loop(
        self, session, jp_country, monkeypatch
    ):
        """A raises, its failure is recorded, then B is still processed."""
        config = load_country_config("jp")
        config.bounds.max_pages = 10
        engine = CountryExplorationEngine(session, config, _NullSearchProvider())

        bad_url = "https://rollback-loop.example.com/bad"
        good_url = "https://rollback-loop.example.com/good"
        # `bad` is left uncommitted, so the handler's rollback discards its row
        # and its instance becomes unusable — the exact live crash.
        _seed_committed_then_pending(
            engine.frontier, jp_country, session, good_url, bad_url
        )

        processed: list[str] = []

        async def fake_process(candidate, run_id):
            processed.append(candidate.url)
            if candidate.url == bad_url:
                raise RuntimeError("simulated candidate failure")

        monkeypatch.setattr(engine, "_process_candidate", fake_process)

        # Must return normally. With the instance-based handler this raises
        # ObjectDeletedError out of the handler and kills the run.
        await engine._frontier_loop(uuid.uuid4(), time.monotonic() + 60)

        assert bad_url in processed, "failing candidate should have been attempted"
        assert good_url in processed, "loop must continue past the failing candidate"

    @pytest.mark.asyncio
    async def test_failed_candidate_is_recorded_not_retried_as_fatal(
        self, session, jp_country, monkeypatch
    ):
        """The failure lands in the row exactly like any other transient error."""
        config = load_country_config("jp")
        config.bounds.max_pages = 10
        config.bounds.max_retries = 50
        engine = CountryExplorationEngine(session, config, _NullSearchProvider())

        bad_url = "https://rollback-recorded.example.com/bad"
        candidate = _add(engine.frontier, jp_country, bad_url, priority=0)
        _commit_setup(session)

        async def always_fail(candidate, run_id):
            raise RuntimeError("simulated candidate failure")

        monkeypatch.setattr(engine, "_process_candidate", always_fail)

        await engine._frontier_loop(uuid.uuid4(), time.monotonic() + 60)

        session.expire_all()
        row = session.get(DiscoveryFrontier, candidate.candidate_id)
        assert row is not None
        assert row.state == FrontierState.PENDING, "under the retry cap: re-queued"
        assert row.retry_count >= 1
        history = row.outcome["history"]
        assert history[-1]["event"] == "transient_error"
        assert "simulated candidate failure" in history[-1]["error"]
        assert engine.metrics.retries >= 1


# ----------------------------------------------------------------------
# Test 2 — the ORM instance really is unusable after a rollback
# ----------------------------------------------------------------------


class TestInstanceInvalidAfterRollback:
    def test_expired_instance_raises_object_deleted_error(
        self, session, jp_country, repo
    ):
        """Pin the mechanism itself: touching the instance raises.

        The row is committed, the instance is loaded, the row is then removed
        and the instance expired — exactly the post-rollback shape the live
        crash had. This asserts the failure is real, so the tests below are
        proving a fix rather than papering over a phantom.
        """
        from sqlalchemy.orm.exc import ObjectDeletedError

        url = "https://rollback-expired.example.com/page"
        row = _add(repo, jp_country, url)
        session.flush()
        session.commit()  # engine-side commits are savepoints under this fixture
        candidate_id = row.candidate_id
        loaded = session.get(DiscoveryFrontier, candidate_id)
        assert loaded is not None

        session.execute(
            text("DELETE FROM discovery_frontier WHERE candidate_id = :c"),
            {"c": candidate_id},
        )
        session.commit()

        with pytest.raises(ObjectDeletedError):
            _ = loaded.url

    def test_handler_on_dead_instance_uses_id_only(
        self, session, jp_country, repo
    ):
        """The handler path completes even when the instance is unusable."""
        from sqlalchemy.orm.exc import ObjectDeletedError

        url = "https://rollback-handler.example.com/page"
        row = _add(repo, jp_country, url)
        session.flush()
        session.commit()
        candidate_id = row.candidate_id
        dead = session.get(DiscoveryFrontier, candidate_id)
        session.execute(
            text("DELETE FROM discovery_frontier WHERE candidate_id = :c"),
            {"c": candidate_id},
        )
        session.commit()

        with pytest.raises(ObjectDeletedError):
            _ = dead.url

        # This is what _frontier_loop's handler now does. It must not raise.
        assert repo.mark_failed_by_id(candidate_id, "boom", max_retries=3) is False


# ----------------------------------------------------------------------
# Test 3 — candidate row gone after rollback is not fatal
# ----------------------------------------------------------------------


class TestMissingCandidateAfterRollback:
    def test_row_discarded_by_rollback_returns_false(self, session, jp_country, repo):
        """A candidate first written inside the aborted transaction is absent."""
        url = "https://rollback-missing.example.com/page"
        row = _add(repo, jp_country, url)
        session.flush()
        candidate_id = row.candidate_id

        session.rollback()  # discards the uncommitted row

        assert repo.mark_failed_by_id(candidate_id, "boom", max_retries=3) is False

    def test_none_candidate_id_is_safe(self, session, jp_country, repo):
        assert repo.mark_failed_by_id(None, "boom", max_retries=3) is False

    def test_unknown_candidate_id_is_safe(self, session, repo):
        assert repo.mark_failed_by_id(uuid.uuid4(), "boom", max_retries=3) is False

    @pytest.mark.asyncio
    async def test_loop_survives_candidate_whose_row_vanished(
        self, session, jp_country, monkeypatch
    ):
        """End to end: the vanished-row path still lets the loop continue."""
        config = load_country_config("jp")
        config.bounds.max_pages = 10
        engine = CountryExplorationEngine(session, config, _NullSearchProvider())

        doomed_url = "https://rollback-vanishing.example.com/doomed"
        survivor_url = "https://rollback-vanishing.example.com/survivor"
        doomed = _add(engine.frontier, jp_country, doomed_url, priority=0)
        _add(engine.frontier, jp_country, survivor_url, priority=1)
        doomed_id = doomed.candidate_id
        _commit_setup(session)

        processed: list[str] = []

        async def fake_process(candidate, run_id):
            processed.append(candidate.url)
            if candidate.url == doomed_url:
                # The row is gone by the time the handler runs: mimic a nested
                # rollback elsewhere in the pipeline discarding this
                # transaction's work, then surface the failure.
                session.execute(
                    text("DELETE FROM discovery_frontier WHERE candidate_id = :c"),
                    {"c": doomed_id},
                )
                session.commit()
                raise RuntimeError("candidate vanished mid-processing")

        monkeypatch.setattr(engine, "_process_candidate", fake_process)

        await engine._frontier_loop(uuid.uuid4(), time.monotonic() + 60)

        assert survivor_url in processed, "run must continue after a vanished candidate"


# ----------------------------------------------------------------------
# Test 4 — normal failure records identical state to before
# ----------------------------------------------------------------------


class TestRetrySemanticsUnchanged:
    def test_by_id_matches_instance_path_under_retry_cap(
        self, session, jp_country, repo
    ):
        """Identical outcome whether the row is reached by id or by instance."""
        a = _add(repo, jp_country, "https://retry-a.example.com/a")
        b = _add(repo, jp_country, "https://retry-b.example.com/b")
        session.flush()

        will_retry = repo.mark_failed_by_id(a.candidate_id, "timeout", max_retries=3)
        session.expire_all()
        row_a = session.get(DiscoveryFrontier, a.candidate_id)
        control_b = session.get(DiscoveryFrontier, b.candidate_id)

        assert will_retry is True
        assert row_a.state == FrontierState.PENDING
        assert row_a.retry_count == 1
        assert row_a.next_retry_at is not None
        assert row_a.lease_expires_at is None

        # Control: the original instance-based method, unchanged.
        assert repo.mark_failed_transient(control_b, "timeout", max_retries=3) is True
        assert control_b.state == row_a.state
        assert control_b.retry_count == row_a.retry_count

    def test_by_id_marks_failed_when_retries_exhausted(
        self, session, jp_country, repo
    ):
        row = _add(repo, jp_country, "https://retry-exhaust.example.com/a")
        session.flush()

        assert repo.mark_failed_by_id(row.candidate_id, "timeout", max_retries=3) is True
        assert repo.mark_failed_by_id(row.candidate_id, "timeout", max_retries=3) is True
        will_retry = repo.mark_failed_by_id(row.candidate_id, "timeout", max_retries=3)

        session.expire_all()
        fresh = session.get(DiscoveryFrontier, row.candidate_id)
        assert will_retry is False
        assert fresh.state == FrontierState.FAILED
        assert fresh.retry_count == 3
        assert fresh.processed_at is not None
        assert fresh.lease_expires_at is None

    def test_history_is_capped_at_ten(self, session, jp_country, repo):
        row = _add(repo, jp_country, "https://retry-history.example.com/a")
        session.flush()
        for i in range(12):
            repo.mark_failed_by_id(row.candidate_id, f"err-{i}", max_retries=99)
        session.expire_all()
        fresh = session.get(DiscoveryFrontier, row.candidate_id)
        history = fresh.outcome["history"]
        assert len(history) == 10
        assert history[-1]["error"] == "err-11"


class _NullSearchProvider:
    """No search results; these tests drive the frontier directly."""

    name = "null"

    async def search(self, query):  # noqa: D102 - test double
        return []
