"""Transaction-scoped isolation for exploration integration tests.

The exploration engine commits its own work, because a run has to be durable.
That makes a naive test session leak fixtures into the shared development
database: the next run of the same test then finds a partly populated frontier
and reports different numbers, and a single committed row can block a later
claim assertion outright.

The transaction itself comes from the shared ``rollback_session`` fixture in
tests/conftest.py; engine-side ``session.commit()`` calls release an inner
SAVEPOINT instead of committing, so nothing the test does survives teardown.

On top of that this fixture resets the country to a known-zero exploration
state inside the transaction: frontier and run history are always cleared, and
any leftover acquisition artifacts from real runs (sources, providers,
scholarships, raw documents) are cleared too, so the zero-seed loop tests
start from a genuinely empty country regardless of what real JP exploration
runs left in the shared development database. (Leftover rows used to starve
the 20-page run budget and push the test's own OFFICIAL_URL candidate into the
second run, breaking the idempotency assertion.) The deletes are part of the
same transaction and are rolled back with everything else.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from database.models.country import Country
from database.models.discovery_frontier import DiscoveryFrontier
from database.models.exploration_run import ExplorationRun
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry

EXPLORATION_TEST_ISO2 = "JP"


@pytest.fixture
def exploration_session(rollback_session):
    """Rollback-only session over an emptied country exploration state."""
    country = (
        rollback_session.query(Country)
        .filter(Country.iso2 == EXPLORATION_TEST_ISO2)
        .first()
    )
    if country is not None:
        cid = country.country_id
        # Children before parents (FKs are RESTRICT); all inside the outer
        # transaction, so the real knowledge base is untouched on teardown.
        rollback_session.execute(
            delete(RawDocument).where(
                RawDocument.source_id.in_(
                    rollback_session.query(SourceRegistry.source_id).filter(
                        SourceRegistry.country_id == cid
                    )
                )
            )
        )
        scholarship_ids = (
            rollback_session.query(Scholarship.scholarship_id)
            .filter(Scholarship.country_id == cid)
            .scalar_subquery()
        )
        rollback_session.execute(
            delete(ScholarshipVersion).where(
                ScholarshipVersion.scholarship_id.in_(scholarship_ids)
            )
        )
        rollback_session.execute(
            delete(Scholarship).where(Scholarship.country_id == cid)
        )
        rollback_session.execute(
            delete(SourceRegistry).where(SourceRegistry.country_id == cid)
        )
        rollback_session.execute(
            delete(DiscoveryFrontier).where(
                DiscoveryFrontier.country_id == cid
            )
        )
        rollback_session.execute(
            delete(ExplorationRun).where(ExplorationRun.country_id == cid)
        )
        # A provider belongs to one country but is *referenced* by sources in
        # any country — real exploration finds "Study in Japan" from a GB or SG
        # search and attaches the JP provider to that source. Deleting only the
        # country's own SourceRegistry rows therefore left those sources
        # holding a reference to a provider about to be deleted, and
        # source_registry_provider_id_fkey is ON DELETE RESTRICT. The fixture
        # broke the moment real cross-country discovery data existed, which is
        # a property of the data, not of any one test run.
        #
        # Clearing the pointer (rather than deleting the other country's
        # sources) keeps the real knowledge base intact and makes the JP
        # provider delete legal inside the rolled-back transaction.
        jp_provider_ids = rollback_session.query(Provider.provider_id).filter(
            Provider.country_id == cid
        )
        rollback_session.execute(
            SourceRegistry.__table__.update()
            .where(SourceRegistry.provider_id.in_(jp_provider_ids))
            .values(provider_id=None)
        )
        rollback_session.execute(
            delete(Provider).where(Provider.country_id == cid)
        )
    return rollback_session
