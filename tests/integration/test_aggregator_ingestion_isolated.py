"""PostgreSQL integration coverage for aggregator checkpoint persistence.

This test deliberately has no dependency on the root conftest (which seeds the
configured development database). It only connects when an explicitly named
disposable PostgreSQL database is supplied.
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from database.models import Base
from services.aggregator_discovery import ingestion
from services.aggregator_discovery.adapters import AggregatorCandidate, AggregatorSource


def _disposable_database_url():
    value = os.environ.get("POLARIS_AGGREGATOR_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("set POLARIS_AGGREGATOR_TEST_DATABASE_URL to an isolated disposable PostgreSQL database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        pytest.fail("aggregator integration tests require PostgreSQL")
    if url.host not in (None, "localhost", "127.0.0.1", "::1"):
        pytest.fail("refusing non-local database host for disposable integration test")
    if not re.search(r"(?:_test|_scratch)$", url.database or "", re.IGNORECASE):
        pytest.fail("refusing database name without explicit _test or _scratch suffix")
    return url


@pytest.fixture
def isolated_session():
    engine = create_engine(_disposable_database_url())
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_bounded_runner_persists_unresolved_candidate_without_scholarship(
    isolated_session, monkeypatch
):
    config = AggregatorSource(
        id="test_aggregator",
        name="Test Aggregator",
        base_url="https://aggregator.example/",
        discovery_urls=("https://aggregator.example/archive/",),
        max_pages=1,
    )
    candidate = AggregatorCandidate(
        source_id=config.id,
        url="https://aggregator.example/page/oddity-scholarship/",
        canonical_url="https://aggregator.example/page/oddity-scholarship",
        title="Oddity Scholarship",
        discovered_from=config.discovery_urls[0],
        discovery_method="html_archive",
        page_intent="UNKNOWN",
        listing_verdict="UNKNOWN",
    )

    async def discover(_config):
        return [candidate]

    class FakeConnector:
        def __init__(self, _config):
            pass

        async def connect(self):
            pass

        async def fetch(self, url):
            return SimpleNamespace(
                final_url=url,
                raw_content=(
                    "<html><head><title>Scholarships</title></head><body>"
                    "<h1>Scholarships</h1><a href='/award-one/'>Award One</a>"
                    "<a href='/award-two/'>Award Two</a></body></html>"
                ),
                status_code=200,
                content_type="html",
            )

        async def close(self):
            pass

    monkeypatch.setattr(ingestion, "discover_source_candidates", discover)
    monkeypatch.setattr(
        "services.ingestion.connectors.generic_playwright.GenericPlaywrightConnector",
        FakeConnector,
    )

    results = await ingestion.run_configured_source(isolated_session, config)

    assert len(results) == 1
    assert results[0].state == "pending_review"
    assert results[0].blockers == ("article_not_confirmed_as_single_scholarship",)
    from database.models.raw_document import RawDocument
    from database.models.scholarship import Scholarship
    from database.models.source_registry import SourceRegistry

    assert isolated_session.query(Scholarship).count() == 0
    source = isolated_session.query(SourceRegistry).one()
    assert source.country_id is None
    assert source.provider_id is None
    assert source.verification_state == "NEEDS_REVIEW"
    assert source.scholarship_page_urls[0]["article_document_id"]
    document = isolated_session.query(RawDocument).one()
    assert document.source_url == candidate.url
