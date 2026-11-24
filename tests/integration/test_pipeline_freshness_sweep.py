"""The scheduled pipeline must run the freshness sweep.

``ScholarshipRepository.reclassify_deadline_states`` existed and was
tested, but only tests ever called it: the nightly entry point
(``scripts/pipeline_run.py``) never did, so a published record whose
deadline passed stayed 'active' in the public API indefinitely. These
tests pin the wiring, not the classification itself.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from scripts.pipeline_run import _freshness_sweep

pytestmark = pytest.mark.integration


@pytest.fixture
def session(rollback_session):
    return rollback_session


def _stale_active_record(session) -> Scholarship:
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"SWEEP_{suffix}".upper()[:32],
        provider_name="Sweep Test Provider",
        provider_type=ProviderType.GOVERNMENT,
        country_id=country.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Sweep Source {suffix}",
        country_id=country.country_id,
        official_url=f"https://www.studyinjapan.go.jp/{suffix}/",
        crawl_entry_url=f"https://www.studyinjapan.go.jp/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id

    scholarship = Scholarship(
        scholarship_name="Sweep Test Scholarship 2027",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        official_page_url="https://www.studyinjapan.go.jp/en/",
        degree="Master",
        funding_type="Fully Funded",
        extraction_status="approved",
        deadline_state="active",  # stale: the deadline below already passed
        provenance_origin="exploration",
    )
    session.add(scholarship)
    session.flush()
    session.add(
        ScholarshipTimeline(
            scholarship_id=scholarship.scholarship_id,
            application_deadline=date.today() - timedelta(days=3),
        )
    )
    session.flush()
    return scholarship


def test_pipeline_sweep_reclassifies_stale_active_records(session):
    row = _stale_active_record(session)

    changed = _freshness_sweep(session)

    assert changed >= 1
    session.refresh(row)
    assert row.deadline_state == "expired"


def test_pipeline_sweep_is_idempotent(session):
    _stale_active_record(session)
    assert _freshness_sweep(session) >= 1
    assert _freshness_sweep(session) == 0
