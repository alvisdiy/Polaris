"""The nightly pipeline's discover step acquires scholarships.

pipeline_run hard-coded run_scholarship_discovery=False, so --discover
grew the provider list but never the catalogue: the registry
acquisition path existed and was exercised by run_country_coverage,
just never by the scheduler's entry point. These tests pin the wiring
(and the operator opt-out), with the orchestrator and crawl replaced
at their module seams.

The main case also runs the enrich step for real: when the --llm pass
landed in enrich_records, pipeline_run's hand-built argument object
was not updated and nightly enrichment silently failed on an
AttributeError the step's error handler swallowed. Running it here
keeps that contract visible.
"""

from __future__ import annotations

import types

import pytest

import database.session as session_module
import scripts.run_country_crawl as crawl_module
import services.ingestion.country_coverage_orchestrator as orchestrator_module
from scripts.pipeline_run import _run_country

pytestmark = pytest.mark.integration


class _FakeOrchestrator:
    calls: list[dict] = []

    def __init__(self, iso2, session):
        self.metrics = types.SimpleNamespace(
            providers_discovered=2, sources_discovered=3, scholarships_persisted=7
        )

    async def run_full_coverage(self, **kwargs):
        _FakeOrchestrator.calls.append(kwargs)
        return self.metrics


async def _fake_crawl_country(iso2, **kwargs):
    return types.SimpleNamespace(
        sources_processed=1,
        sources_skipped=0,
        pages_fetched=0,
        candidates=0,
        extraction_succeeded=0,
        extraction_failed=0,
        persisted=0,
        duplicates=0,
        errors=0,
    )


def _args(**overrides):
    args = types.SimpleNamespace(
        discover=True,
        no_scholarship_discovery=False,
        max_sources=5,
        max_pages_per_source=4,
        max_total_pages=50,
        runtime=5,
        skip_recent_days=0,
        allow_non_scratch=True,
        no_enrich=False,
        no_auto_review=True,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


@pytest.fixture(autouse=True)
def _seams(monkeypatch, exploration_session):
    _FakeOrchestrator.calls = []
    monkeypatch.setattr(session_module, "SessionLocal", lambda: exploration_session)
    monkeypatch.setattr(crawl_module, "ensure_seed_sources", lambda session, iso2: 1)
    monkeypatch.setattr(crawl_module, "crawl_country", _fake_crawl_country)
    monkeypatch.setattr(
        orchestrator_module, "CountryCoverageOrchestrator", _FakeOrchestrator
    )


@pytest.mark.asyncio
async def test_discover_acquires_scholarships_by_default():
    record = await _run_country("JP", _args())
    assert record["errors"] == []
    assert _FakeOrchestrator.calls[0]["run_scholarship_discovery"] is True
    assert _FakeOrchestrator.calls[0]["max_urls_per_source"] == 4
    assert record["steps"]["scholarships_persisted"] == 7
    # The enrich step ran against the real enrich_records.run: the
    # argument-object contract (incl. the llm attributes) holds.
    assert record["steps"]["enrich"] == "ran"


@pytest.mark.asyncio
async def test_operator_can_opt_out_of_scholarship_acquisition():
    record = await _run_country("JP", _args(no_scholarship_discovery=True))
    assert record["errors"] == []
    assert _FakeOrchestrator.calls[0]["run_scholarship_discovery"] is False
