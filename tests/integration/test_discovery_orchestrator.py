"""DiscoveryOrchestrator (services/ingestion/discovery.py).

This legacy per-source orchestrator sat at 27% coverage while deciding
what enters the knowledge base: URL dedup, checksum dedup, fetch
failures, extraction outcomes and the pending-document reprocessing
pass were all unmeasured. These tests drive the real orchestrator
against the scratch database with the connector and the extraction
pipeline replaced at their seams — the pipeline functions are imported
function-locally by the module, so the seams are the orchestrator
module's attributes.
"""

from __future__ import annotations

import hashlib
import types
import uuid
from datetime import datetime, timezone

import pytest

import services.ingestion.orchestrator as pipeline_module
from database.models.country import Country
from database.models.raw_document import RawDocument
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors import FetchResult
from services.ingestion.discovery import DiscoveryOrchestrator

pytestmark = pytest.mark.integration


def _make_source(session):
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]
    source = SourceRegistry(
        source_name=f"Discovery test {suffix}",
        country_id=jp.country_id,
        official_url=f"https://example.org/{suffix}/",
        crawl_entry_url=f"https://example.org/{suffix}/en/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add(source)
    session.flush()
    return source.source_id


@pytest.fixture
def source_id(exploration_session):
    return _make_source(exploration_session)


class FakeConnector:
    def __init__(self, source_id, urls=(), *, fetch_error: Exception | None = None):
        self.config = types.SimpleNamespace(source_id=source_id)
        self._urls = list(urls)
        self._fetch_error = fetch_error
        self.fetched: list[str] = []

    async def discover(self):
        return list(self._urls)

    async def fetch(self, url):
        self.fetched.append(url)
        if self._fetch_error is not None:
            raise self._fetch_error
        return FetchResult(
            source_id=self.config.source_id,
            raw_content=f"<html><body>Programme page for {url}</body></html>",
            content_type="html",
            final_url=url,
            status_code=200,
            processing_time_ms=1.0,
            retry_count=0,
        )


def _pipeline_result(is_valid: bool):
    return types.SimpleNamespace(
        is_valid=is_valid,
        validation_report=types.SimpleNamespace(issues=[] if is_valid else ["no deadline"]),
    )


@pytest.fixture
def pipeline(monkeypatch):
    """Replace run_pipeline/persist_scholarship; returns the control dict."""
    control = {"valid": True, "persist": True, "pipeline_calls": 0, "persist_calls": 0}

    def fake_run_pipeline(document_id, session, llm_client):
        control["pipeline_calls"] += 1
        return _pipeline_result(control["valid"])

    def fake_persist(result, document_id, session):
        control["persist_calls"] += 1
        return control["persist"]

    monkeypatch.setattr(pipeline_module, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(pipeline_module, "persist_scholarship", fake_persist)
    return control


def _seed_document(session, source_id, url, content="already fetched content", status="pending"):
    doc = RawDocument(
        source_id=source_id,
        source_url=url,
        content_type="html",
        raw_content=content,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        status_code=200,
        fetched_at=datetime.now(timezone.utc),
        processing_status=status,
    )
    session.add(doc)
    session.flush()
    return doc


class TestDiscoverAndProcess:
    @pytest.mark.asyncio
    async def test_no_candidates_finalizes_cleanly(self, exploration_session, source_id, pipeline):
        orch = DiscoveryOrchestrator(FakeConnector(source_id, []), exploration_session)
        metrics = await orch.discover_and_process()
        assert metrics.candidate_urls_found == 0
        assert metrics.finished_at is not None
        assert metrics.to_dict()["persisted"] == 0

    @pytest.mark.asyncio
    async def test_filter_limit_seen_and_happy_path(
        self, exploration_session, source_id, pipeline
    ):
        urls = [f"https://example.org/p{i}" for i in range(4)]
        _seed_document(exploration_session, source_id, urls[0], status="processed")
        connector = FakeConnector(source_id, urls)
        orch = DiscoveryOrchestrator(connector, exploration_session)

        metrics = await orch.discover_and_process(
            url_filter=lambda u: not u.endswith("p3"), max_urls=2
        )
        # Filter drops p3 (3 left), limit keeps p0+p1, p0 is already seen.
        assert metrics.candidate_urls_found == 4
        assert metrics.urls_after_filter == 3
        assert metrics.urls_already_seen == 1
        assert connector.fetched == [urls[1]]
        assert metrics.fetch_succeeded == 1
        # Persisted twice, not once: the freshly saved document is still
        # "pending" (nothing in the pipeline flips its status), so the
        # same run's reprocess pass runs it again. Downstream dedup is
        # what makes that wasteful rather than wrong.
        assert metrics.persisted == 2
        assert metrics.extraction_succeeded == 2

    @pytest.mark.asyncio
    async def test_checksum_duplicate_skips_the_pipeline(
        self, exploration_session, source_id, pipeline
    ):
        url = "https://example.org/dup"
        connector = FakeConnector(source_id, [url])
        # Same content under a different URL: URL dedup cannot catch it,
        # the checksum check must.
        fetched = await connector.fetch(url)
        _seed_document(
            exploration_session,
            source_id,
            "https://example.org/other",
            fetched.raw_content,
            status="processed",
        )
        orch = DiscoveryOrchestrator(connector, exploration_session)
        metrics = await orch.discover_and_process()
        assert metrics.duplicates_skipped == 1
        assert pipeline["pipeline_calls"] == 0
        assert metrics.persisted == 0

    @pytest.mark.asyncio
    async def test_invalid_extraction_and_failed_persist_count_as_failures(
        self, exploration_session, source_id, pipeline
    ):
        connector = FakeConnector(source_id, ["https://example.org/a"])
        orch = DiscoveryOrchestrator(connector, exploration_session)

        pipeline["valid"] = False
        metrics = await orch.discover_and_process()
        # Twice per run, as in the happy path: the URL loop and the
        # same-run reprocess of the still-pending document.
        assert metrics.extraction_failed == 2
        assert metrics.persisted == 0

        pipeline["valid"] = True
        pipeline["persist"] = False
        # A second source: the first half's document is still pending
        # under the first source and would (correctly) be reprocessed
        # by any run of that source, polluting these counts.
        source_id2 = _make_source(exploration_session)
        connector2 = FakeConnector(source_id2, ["https://example.org/b"])
        orch2 = DiscoveryOrchestrator(connector2, exploration_session)
        metrics2 = await orch2.discover_and_process()
        assert metrics2.extraction_failed == 2
        assert metrics2.persisted == 0

    @pytest.mark.asyncio
    async def test_a_fetch_failure_is_recorded_and_the_run_survives(
        self, exploration_session, source_id, pipeline
    ):
        connector = FakeConnector(
            source_id, ["https://example.org/boom"], fetch_error=RuntimeError("socket closed")
        )
        orch = DiscoveryOrchestrator(connector, exploration_session)
        metrics = await orch.discover_and_process()
        assert metrics.fetch_failed >= 1
        assert any("boom" in e for e in metrics.errors)
        assert metrics.finished_at is not None

    @pytest.mark.asyncio
    async def test_a_discovery_failure_finalizes_with_the_error(
        self, exploration_session, source_id, pipeline
    ):
        class ExplodingConnector(FakeConnector):
            async def discover(self):
                raise RuntimeError("listing page gone")

        orch = DiscoveryOrchestrator(ExplodingConnector(source_id), exploration_session)
        metrics = await orch.discover_and_process()
        assert any("listing page gone" in e for e in metrics.errors)
        assert metrics.finished_at is not None


class TestReprocessPending:
    @pytest.mark.asyncio
    async def test_valid_pending_document_is_processed_and_marked(
        self, exploration_session, source_id, pipeline
    ):
        doc = _seed_document(exploration_session, source_id, "https://example.org/pending")
        orch = DiscoveryOrchestrator(FakeConnector(source_id, []), exploration_session)
        await orch._reprocess_pending_documents()
        exploration_session.refresh(doc)
        assert doc.processing_status == "processed"
        assert orch.metrics.persisted == 1

    @pytest.mark.asyncio
    async def test_invalid_pending_document_stays_pending(
        self, exploration_session, source_id, pipeline
    ):
        pipeline["valid"] = False
        doc = _seed_document(exploration_session, source_id, "https://example.org/still-bad")
        orch = DiscoveryOrchestrator(FakeConnector(source_id, []), exploration_session)
        await orch._reprocess_pending_documents()
        exploration_session.refresh(doc)
        assert doc.processing_status == "pending"
        assert orch.metrics.extraction_failed == 1
