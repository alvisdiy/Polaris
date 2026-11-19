"""Benchmark measurement must be run-scoped, not corpus-scoped.

The first benchmark harness reported ``count(*) FROM scholarship`` as though it
were a discovery result. These tests pin the opposite behaviour: every number a
run reports is scoped to that run, provenance is read from immutable
observations rather than the frozen ``origin_query`` column, uniqueness is the
canonical identity, and approval is never inferred.

Rollback-isolated against the shared development database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from database.models.country import Country
from database.models.discovery_frontier import DiscoveryFrontier
from database.models.enums import ProviderType
from database.models.exploration_run import ExplorationRun, ExplorationRunStatus
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.exploration import benchmark_metrics as bm
from services.exploration.config_loader import CountryExplorationConfig
from services.exploration.query_generation import QueryGenerator
from services.exploration.repositories.frontier_repository import (
    FrontierObservation,
    FrontierRepository,
)
from services.exploration.repositories.run_repository import RunRepository  # noqa: F401


@pytest.fixture
def session(exploration_session):
    return exploration_session


@pytest.fixture
def conn(session):
    return session.connection()


@pytest.fixture
def jp(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


def _config(**overrides) -> CountryExplorationConfig:
    base = dict(
        iso2="JP",
        country_name="Japan",
        country_local="日本",
        query_families=[
            "opportunity", "official_source", "funding",
            "degree", "ecosystem", "provider", "localized",
        ],
        max_queries_per_run=12,
        terminology={
            "scholarship": ["scholarship", "fellowship", "奨学金"],
            "education": ["master", "phd"],
            "provider": ["university", "government"],
            "funding": ["fully funded", "stipend"],
        },
    )
    base.update(overrides)
    return CountryExplorationConfig(**base)


def _make_run(session, jp, config, metrics):
    repo = RunRepository(session)
    run = repo.start_run(jp.country_id, config=config.model_dump(), bounds={})
    record = dict(metrics)
    record["runtime_seconds"] = 1.0
    repo.finish_run(run, "completed", record)
    session.commit()
    return str(run.run_id)


def _engine_offset(session, jp) -> int:
    """The rotation offset the engine would use for a run right now.

    The engine generates its plan inside ``_seed_frontier``, after
    ``start_run`` has committed this run's own row, so the offset is an
    INCLUSIVE count of the country's runs. Tests must mirror that or they
    assert against a plan the engine never executed.
    """
    from database.models.exploration_run import ExplorationRun

    return session.query(ExplorationRun).filter(
        ExplorationRun.country_id == jp.country_id
    ).count()


def _observe(session, jp, run_id, url, query, *, origin="web_search", priority=5):
    """Record one discovery observation by `run_id` for `url`."""
    repo = FrontierRepository(session)
    repo.upsert_candidate(
        jp.country_id,
        url,
        origin=origin,
        candidate_type="opportunity",
        origin_query=query,
        observation=FrontierObservation(
            origin=origin, origin_query=query, rank=1, run_id=str(run_id)
        ),
        priority=priority,
        run_id=run_id,
    )
    session.commit()


# ------------------------------------------------------------------- B1


class TestRunScopedFunnel:
    def test_two_runs_report_independent_metrics(self, session, conn, jp):
        """A reports its own 3 candidates, B its own 5. Never 8 and 8."""
        config = _config()
        run_a = _make_run(session, jp, config, {
            "queries_executed": 12, "discovery_queries": 12, "search_results": 30,
            "pages_fetched": 9, "candidates_created": 3,
        })
        run_b = _make_run(session, jp, config, {
            "queries_executed": 12, "discovery_queries": 12, "search_results": 50,
            "pages_fetched": 15, "candidates_created": 5,
        })
        for i in range(3):
            _observe(session, jp, run_a, f"https://a{i}.example.com/p", "scholarship Japan")
        for i in range(5):
            _observe(session, jp, run_b, f"https://b{i}.example.com/p", "scholarship Japan")

        a = bm.run_funnel(conn, run_a)
        b = bm.run_funnel(conn, run_b)

        assert a["discovery"]["frontier_created"]["value"] == 3
        assert b["discovery"]["frontier_created"]["value"] == 5
        assert a["search"]["queries_executed"]["value"] == 12
        assert b["search"]["search_results"]["value"] == 50
        assert a["fetch"]["pages_fetched"]["value"] == 9
        assert b["fetch"]["pages_fetched"]["value"] == 15

    def test_queries_authority_is_the_difference_not_a_guess(self, session, conn, jp):
        config = _config()
        run_id = _make_run(session, jp, config, {
            "queries_executed": 30, "discovery_queries": 12, "search_results": 100,
        })
        funnel = bm.run_funnel(conn, run_id)
        assert funnel["search"]["queries_discovery"]["value"] == 12
        assert funnel["search"]["queries_authority"]["value"] == 18

    def test_every_funnel_entry_declares_its_source(self, session, conn, jp):
        """No metric may be reported without saying where it came from."""
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12, "pages_fetched": 1})
        funnel = bm.run_funnel(conn, run_id)
        for section in ("search", "discovery", "fetch", "extraction", "identity"):
            for metric, payload in funnel[section].items():
                assert payload["source"], f"{section}.{metric} has no declared source"
                assert "recorded" in payload

    def test_all_time_totals_are_never_a_run_result(self, session, conn, jp):
        """The corpus snapshot must be labelled and held apart from the funnel."""
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12})
        funnel = bm.run_funnel(conn, run_id)

        assert "not_run_scopable" in funnel
        assert "NOT a benchmark run result" in funnel["not_run_scopable"]["all_time_snapshot"]["scope"]
        # The run's own scholarship numbers start at zero regardless of corpus size.
        scholarships = bm.run_scholarship_funnel(conn, run_id)
        assert scholarships["new_unique_scholarships"] == 0
        assert scholarships["candidate_scholarship_rows"] == 0


# ------------------------------------------------- extraction honesty


class TestExtractionMetrics:
    def test_missing_extraction_counter_reports_not_measured(self, session, conn, jp):
        """A counter this run never recorded must not be reported as zero."""
        config = _config()
        run_id = _make_run(session, jp, config, {
            "queries_executed": 12, "pages_fetched": 5, "extraction_failures": 2,
        })
        funnel = bm.run_funnel(conn, run_id)
        assert funnel["extraction"]["extraction_success"]["recorded"] is False
        assert funnel["extraction"]["extraction_success"]["value"] is None
        assert funnel["extraction"]["extraction_attempts"]["value"] is None

    def test_recorded_extraction_counter_is_used(self, session, conn, jp):
        config = _config()
        run_id = _make_run(session, jp, config, {
            "queries_executed": 12, "pages_fetched": 5,
            "extraction_succeeded": 3, "extraction_failures": 2,
            "duplicates_collapsed": 1,
        })
        funnel = bm.run_funnel(conn, run_id)
        assert funnel["extraction"]["extraction_success"]["value"] == 3
        assert funnel["extraction"]["extraction_attempts"]["value"] == 5
        assert funnel["extraction"]["candidate_scholarships"]["value"] == 4


# ------------------------------------------------------------------- B2


class TestProvenanceIntegrity:
    def test_shared_frontier_row_keeps_both_runs_observations(self, session, conn, jp):
        """Run A and Run B both see URL X; each attribution must survive."""
        config = _config()
        run_a = _make_run(session, jp, config, {"queries_executed": 12})
        run_b = _make_run(session, jp, config, {"queries_executed": 12})

        url = "https://shared.example.com/scholarship"
        _observe(session, jp, run_a, url, "fully funded scholarship Japan")
        _observe(session, jp, run_b, url, "ministry of education fellowship Japan")

        from services.exploration.url_utils import url_hash

        row = session.query(DiscoveryFrontier).filter_by(
            country_id=jp.country_id, url_hash=url_hash(url)
        ).one()

        provenance = bm.candidate_provenance(conn, row.candidate_id)
        assert provenance["discovery_run_id"] == run_a, "creation run must not change"
        assert set(provenance["observed_by_runs"]) == {run_a, run_b}
        assert len(provenance["observations"]) == 2

    def test_origin_query_column_is_frozen_at_first_discovery(self, session, conn, jp):
        """The column answers 'first seen', which is why attribution reads events."""
        config = _config()
        run_a = _make_run(session, jp, config, {"queries_executed": 12})
        run_b = _make_run(session, jp, config, {"queries_executed": 12})
        url = "https://frozen.example.com/scholarship"
        _observe(session, jp, run_a, url, "query-from-A")
        _observe(session, jp, run_b, url, "query-from-B")

        from services.exploration.url_utils import url_hash

        row = session.query(DiscoveryFrontier).filter_by(
            country_id=jp.country_id, url_hash=url_hash(url)
        ).one()
        assert row.origin_query == "query-from-A"

        a_obs = {o["origin_query"] for o in bm.run_observations(conn, run_a)}
        b_obs = {o["origin_query"] for o in bm.run_observations(conn, run_b)}
        assert a_obs == {"query-from-A"}
        assert b_obs == {"query-from-B"}, "run B must see its own query, not A's"

    def test_family_attribution_uses_this_runs_observations_only(self, session, conn, jp):
        config = _config()
        run_a = _make_run(session, jp, config, {"queries_executed": 12})
        run_b = _make_run(session, jp, config, {"queries_executed": 12})
        plan = {
            q.text: q.family
            for q in QueryGenerator(config).generate_plan(run_offset=_engine_offset(session, jp))
        }
        funding_query = next(t for t, f in plan.items() if f == "funding")
        ecosystem_query = next(t for t, f in plan.items() if f == "ecosystem")

        _observe(session, jp, run_a, "https://fa.example.com/p", funding_query)
        _observe(session, jp, run_b, "https://fb.example.com/p", ecosystem_query)

        buckets = bm.repeat_attribution(conn, run_a, plan)
        assert set(buckets) == {"funding"}
        assert buckets["funding"]["observations"] == 1


# ------------------------------------------------------------------- B3


class TestQueryRepetition:
    def test_repeated_queries_are_disclosed_not_counted_as_breadth(self, session, conn, jp):
        config = _config()
        run_a = _make_run(session, jp, config, {"queries_executed": 12})
        first = QueryGenerator(config).generate_plan(run_offset=_engine_offset(session, jp))
        for query in first[:3]:
            _observe(session, jp, run_a, f"https://r{abs(hash(query))}.example.com/p", query.text)

        rep = bm.query_repetition(
            conn, jp.country_id, {q.text: q.family for q in first[:3]}
        )
        assert rep["queries_planned"] == 3
        assert rep["queries_repeated_from_previous_run"] == 3
        assert rep["queries_new_to_this_country"] == 0

    def test_fresh_queries_are_reported_as_new(self, session, conn, jp):
        config = _config()
        _make_run(session, jp, config, {"queries_executed": 12})
        rep = bm.query_repetition(conn, jp.country_id, {"never issued before": "funding"})
        assert rep["queries_repeated_from_previous_run"] == 0
        assert rep["queries_new_to_this_country"] == 1

    def test_plan_is_deterministic_across_offsets(self):
        """The generator must be reproducible or no run is reproducible."""
        config = _config()
        a = [q.text for q in QueryGenerator(config).generate_plan(run_offset=0)]
        b = [q.text for q in QueryGenerator(config).generate_plan(run_offset=0)]
        assert a == b
        c = {q.text for q in QueryGenerator(config).generate_plan(run_offset=3)}
        assert set(a) != c, "rotation must move the plan"


# --------------------------------------------------------------- D1 / D2


def _link_scholarship(session, jp, conn, run_id, candidate_id, *, name, status, identity):
    """Register a source produced by `run_id` and hang a scholarship off it."""
    country_id = jp.country_id
    provider = Provider(
        provider_name=f"provider-{name}",
        provider_code=f"code-{name}".replace(" ", "-"),
        provider_type=ProviderType.UNIVERSITY,
        country_id=country_id,
    )
    session.add(provider)
    session.flush()

    source = SourceRegistry(
        source_name=f"source-{name}",
        country_id=country_id,
        provider_id=provider.provider_id,
        official_url=f"https://{name}.example.com/",
        crawl_entry_url=f"https://{name}.example.com/",
        crawl_method="http",
        connector_name="test",
        crawl_frequency="manual",
        status="Active",
        verification_state="VERIFIED",
        discovered_via={"run_id": str(run_id), "frontier_candidate": str(candidate_id)},
    )
    session.add(source)
    session.flush()

    scholarship = Scholarship(
        scholarship_name=name,
        provider_id=provider.provider_id,
        country_id=country_id,
        source_id=source.source_id,
        official_page_url=f"https://{name.replace(' ', '-').lower()}.example.com/award",
        extraction_status=status,
        provenance_origin="exploration",
        identity_key=identity,
    )
    session.add(scholarship)
    session.commit()
    return scholarship


class TestScholarshipRunAttribution:
    def test_new_scholarship_is_attributed_to_its_run(self, session, conn, jp):
        config = _config()
        run_a = _make_run(session, jp, config, {"queries_executed": 12})
        run_b = _make_run(session, jp, config, {"queries_executed": 12})

        repo = FrontierRepository(session)
        candidate, _ = repo.upsert_candidate(
            jp.country_id, "https://new.example.com/p", origin="web_search",
            origin_query="scholarship Japan", run_id=run_a,
        )
        session.commit()

        _link_scholarship(
            session, jp, conn, run_a, candidate.candidate_id,
            name="New Japan Award", status="pending_review", identity="a" * 64,
        )

        a = bm.run_scholarship_funnel(conn, run_a)
        b = bm.run_scholarship_funnel(conn, run_b)
        assert a["new_unique_scholarships"] == 1
        assert a["pending_review"] == 1
        assert b["new_unique_scholarships"] == 0
        assert b["candidate_scholarship_rows"] == 0

    def test_canonical_identity_is_enforced_by_the_schema(self, session, conn, jp):
        """A repeated identity_key is refused outright.

        The benchmark counts DISTINCT identity_key because production dedup
        makes a second row under one identity impossible: the partial unique
        index ``uq_scholarship_identity`` rejects it. Asserting that the guard
        exists is stronger than asserting a counter behaves, and it is what
        keeps "row count" and "unique scholarship" from drifting apart.
        """
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12})
        repo = FrontierRepository(session)
        cand, _ = repo.upsert_candidate(
            jp.country_id, "https://one.example.com/p", origin="web_search",
            observation=FrontierObservation(
                origin="web_search", origin_query="scholarship Japan", rank=1,
                run_id=str(run_id),
            ),
            run_id=run_id,
        )
        session.commit()
        _link_scholarship(
            session, jp, conn, run_id, cand.candidate_id,
            name="Same Award", status="pending_review", identity="b" * 64,
        )
        assert bm.run_scholarship_funnel(conn, run_id)["new_unique_scholarships"] == 1

        provider = session.query(Provider).filter_by(provider_name="provider-Same Award").one()
        session.add(Scholarship(
            scholarship_name="Same Award (variant spelling)",
            provider_id=provider.provider_id,
            country_id=jp.country_id,
            source_id=session.query(SourceRegistry).filter_by(
                source_name="source-Same Award"
            ).one().source_id,
            official_page_url="https://same-award-variant.example.com/award",
            provenance_origin="exploration",
            extraction_status="pending_review",
            identity_key="b" * 64,
        ))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_approved_before_run_is_not_approved_by_run(self, session, conn, jp):
        """A record approved earlier must not be credited to a later run."""
        config = _config()
        old_run = _make_run(session, jp, config, {"queries_executed": 12})
        repo = FrontierRepository(session)
        cand, _ = repo.upsert_candidate(
            jp.country_id, "https://approved.example.com/p", origin="web_search",
            origin_query="scholarship Japan", run_id=old_run,
        )
        session.commit()
        _link_scholarship(
            session, jp, conn, old_run, cand.candidate_id,
            name="Approved Earlier", status="approved", identity="c" * 64,
        )

        new_run = _make_run(session, jp, config, {"queries_executed": 12})
        report = bm.run_scholarship_funnel(conn, new_run)
        assert report["approved"] == 0
        assert report["new_unique_scholarships"] == 0
        # The corpus snapshot still shows it, but as an all-time total.
        assert bm.all_time_snapshot(conn)["approved"] >= 1


class TestFamilyScholarshipAttribution:
    def test_one_scholarship_two_families_counts_once_globally(self, session, conn, jp):
        """funding + ecosystem reach the same scholarship: global 1, families 1+1."""
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12})
        plan = {
            q.text: q.family
            for q in QueryGenerator(config).generate_plan(run_offset=_engine_offset(session, jp))
        }
        funding_query = next(t for t, f in plan.items() if f == "funding")
        ecosystem_query = next(t for t, f in plan.items() if f == "ecosystem")

        url = "https://twofam.example.com/scholarship"
        repo = FrontierRepository(session)
        candidate, _ = repo.upsert_candidate(
            jp.country_id, url, origin="web_search",
            origin_query=funding_query,
            # The observation is the event-log entry attribution reads. Passing
            # origin_query alone sets the frozen column but records no event,
            # which is exactly the case run-scoped attribution cannot see.
            observation=FrontierObservation(
                origin="web_search", origin_query=funding_query, rank=1,
                run_id=str(run_id),
            ),
            run_id=run_id,
        )
        session.commit()
        # Same run, second query, same candidate: a second observation.
        repo.upsert_candidate(
            jp.country_id, url, origin="web_search",
            origin_query=ecosystem_query,
            observation=FrontierObservation(
                origin="web_search", origin_query=ecosystem_query, rank=2,
                run_id=str(run_id),
            ),
            run_id=run_id,
        )
        session.commit()

        _link_scholarship(
            session, jp, conn, run_id, candidate.candidate_id,
            name="Two Family Award", status="pending_review", identity="d" * 64,
        )

        report = bm.run_scholarship_funnel(conn, run_id)
        assert report["new_unique_scholarships"] == 1
        assert report["by_family"]["funding"]["unique_scholarships"] == 1
        assert report["by_family"]["ecosystem"]["unique_scholarships"] == 1
        assert report["family_sum"] == 2
        assert report["family_sum"] > report["new_unique_scholarships"]

    def test_legacy_rows_are_never_counted_as_engine_discovery(self, session, conn, jp):
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12})
        provider = Provider(
            provider_name="legacy-provider",
            provider_code="legacy-provider",
            provider_type=ProviderType.SCHOLARSHIP_AGENCY,
            country_id=jp.country_id,
        )
        session.add(provider)
        session.flush()
        legacy_source = SourceRegistry(
            source_name="legacy-source",
            country_id=jp.country_id,
            official_url="https://legacy.example.com/",
            crawl_entry_url="https://legacy.example.com/",
            crawl_method="http",
            connector_name="test",
            crawl_frequency="manual",
            status="Active",
            verification_state="VERIFIED",
            # No run_id in discovered_via: this source predates the engine.
            discovered_via={"legacy": "seed_script"},
        )
        session.add(legacy_source)
        session.flush()
        session.add(Scholarship(
            scholarship_name="Hand Seeded Legacy Award",
            provider_id=provider.provider_id,
            country_id=jp.country_id,
            source_id=legacy_source.source_id,
            official_page_url="https://legacy.example.com/award",
            extraction_status="approved",
            provenance_origin="unknown",
            identity_key="e" * 64,
        ))
        session.commit()

        report = bm.run_scholarship_funnel(conn, run_id)
        assert report["new_unique_scholarships"] == 0
        assert report["approved"] == 0

    def test_every_reachable_record_carries_an_identity_key(self, session, conn, jp):
        config = _config()
        run_id = _make_run(session, jp, config, {"queries_executed": 12})
        repo = FrontierRepository(session)
        cand, _ = repo.upsert_candidate(
            jp.country_id, "https://idk.example.com/p", origin="web_search", run_id=run_id,
        )
        session.commit()
        _link_scholarship(
            session, jp, conn, run_id, cand.candidate_id,
            name="Identity Award", status="pending_review", identity="f" * 64,
        )
        assert bm.run_scholarship_funnel(conn, run_id)["identity_keys_missing"] == 0


# ------------------------------------------------------ run accounting


class TestRunAccounting:
    def test_failed_runs_are_separated_from_completed(self, session, conn, jp):
        config = _config()
        good = _make_run(session, jp, config, {"queries_executed": 12})
        bad_row = ExplorationRun(
            country_id=jp.country_id,
            status=ExplorationRunStatus.FAILED,
            config_snapshot=config.model_dump(),
            bounds_snapshot={},
            metrics={"queries_executed": 99},
            started_at=datetime.now(timezone.utc),
        )
        session.add(bad_row)
        session.commit()

        completed, not_completed = bm.exclude_failed_runs(conn, [good, str(bad_row.run_id)])
        assert completed == [good]
        assert str(bad_row.run_id) in not_completed

    def test_unknown_run_id_is_reported_not_silently_dropped(self, session, conn, jp):
        missing = "00000000-0000-0000-0000-000000000000"
        assert bm.run_record(conn, missing) is None
        assert bm.run_funnel(conn, missing)["error"]
        completed, not_completed = bm.exclude_failed_runs(conn, [missing])
        assert completed == []
        assert not_completed == [missing]
