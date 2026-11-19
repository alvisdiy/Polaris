"""Persistence cannot create a duplicate, whichever path created it.

The finding that motivated this suite: `ScholarshipRepository.save()` had no
deduplication check, and only `AcquisitionService._persist_with_dedup()`
looked for an existing identity. The generic ingestion orchestrator, the
discovery service behind it and the seed scripts all wrote through `save()`
unfiltered, so a scholarship re-acquired by a different path produced a
second row.

These tests use the real database and the real repository. `rollback_session`
keeps every row inside a transaction that is discarded afterwards, so the
shared development database is unchanged.
"""

from __future__ import annotations

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.scholarship.identity import (
    IdentityUnavailable,
    scholarship_identity_key,
)
from services.scholarship.mapper import ScholarshipMapper
from services.scholarship.repository import ScholarshipRepository

pytestmark = pytest.mark.integration

# Names that cannot collide with a record another suite leaves in the shared
# database.
BASE_NAME = "Wrenfield Maritime Graduate Award"
VARIANT_NAME = "WRENFIELD   Maritime Graduate Award!"


@pytest.fixture
def world(rollback_session):
    session = rollback_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code="XYZ_IDENTITY",
        provider_name="Wrenfield Trust",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://identity.example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Wrenfield Identity Source",
        country_id=country.country_id,
        official_url="https://identity.example.org/",
        crawl_entry_url="https://identity.example.org/award",
        crawl_method="listing",
        connector_name="generic_playwright",
        crawl_frequency="weekly",
        status="Active",
        verification_state="verified",
    )
    session.add_all([provider, source])
    session.flush()
    return {
        "session": session,
        "provider": provider,
        "country": country,
        "source": source,
    }


def _rows_created(world):
    """Rows this test created.

    The shared development database holds the whole verified knowledge base,
    so an unscoped ``count()`` would assert against other suites' data.
    """
    return (
        world["session"]
        .query(Scholarship)
        .filter(Scholarship.source_id == world["source"].source_id)
    )


def _scholarship(world, *, name=BASE_NAME, status="pending_review", **overrides):
    row = Scholarship(
        scholarship_name=name,
        provider_id=world["provider"].provider_id,
        country_id=world["country"].country_id,
        source_id=world["source"].source_id,
        official_page_url="https://identity.example.org/award",
        extraction_status=status,
        field_of_study=[],
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# --- the invariant ---------------------------------------------------------


def test_second_save_of_the_same_scholarship_returns_the_first_row(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    first = repo.save(_scholarship(world))
    second = repo.save(_scholarship(world))

    assert second.scholarship_id == first.scholarship_id
    assert _rows_created(world).count() == 1


def test_formatting_variant_does_not_create_a_second_row(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    repo.save(_scholarship(world, name=BASE_NAME))
    repo.save(_scholarship(world, name=VARIANT_NAME))

    assert _rows_created(world).count() == 1


def test_a_different_scholarship_gets_its_own_row(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    repo.save(_scholarship(world, name=BASE_NAME))
    repo.save(_scholarship(world, name="Wrenfield Maritime Doctoral Award"))

    assert _rows_created(world).count() == 2


def test_a_different_cycle_of_the_same_programme_gets_its_own_row(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    repo.save(_scholarship(world, name=f"{BASE_NAME} 2026"))
    repo.save(_scholarship(world, name=f"{BASE_NAME} 2027"))

    assert _rows_created(world).count() == 2


def test_every_saved_row_carries_a_canonical_identity(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    repo.save(_scholarship(world))

    saved = _rows_created(world).one()
    assert saved.identity_key == scholarship_identity_key(
        saved.provider_id, saved.scholarship_name, saved.country_id
    )


def test_a_row_with_no_usable_name_is_refused_rather_than_saved(world):
    """Otherwise the row lands permanently outside deduplication."""
    session = world["session"]
    repo = ScholarshipRepository(session)

    with pytest.raises(IdentityUnavailable):
        repo.save(_scholarship(world, name="   "))

    assert _rows_created(world).count() == 0


# --- merge policy ----------------------------------------------------------


def test_dedup_does_not_let_a_rejected_row_overwrite_an_approved_one(world):
    """The single most important merge rule in this phase."""
    session = world["session"]
    repo = ScholarshipRepository(session)

    approved = repo.save(_scholarship(world, status="approved", degree="Master"))
    repo.save(
        _scholarship(
            world,
            status="rejected",
            degree="Doctorate",
            application_url="https://identity.example.org/apply",
        )
    )

    session.refresh(approved)
    assert approved.extraction_status == "approved"
    assert approved.degree == "Master"
    # The rejected row's field must not have landed on the canonical record.
    assert approved.application_url is None


def test_dedup_preserves_the_approved_record_application_url(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    approved = repo.save(
        _scholarship(world, status="approved", application_url="https://identity.example.org/apply")
    )
    repo.save(_scholarship(world, status="pending_review", application_url="https://spam.example.org/"))

    session.refresh(approved)
    assert approved.application_url == "https://identity.example.org/apply"


def test_dedup_does_not_erase_provenance(world):
    session = world["session"]
    repo = ScholarshipRepository(session)

    canonical = repo.save(_scholarship(world, provenance_origin="exploration"))
    repo.save(_scholarship(world, provenance_origin="connector"))

    session.refresh(canonical)
    assert canonical.provenance_origin == "exploration"


# --- the orchestrator path -------------------------------------------------


def test_the_generic_orchestrator_path_is_also_deduplicated(world):
    """`persist_scholarship` never computed an identity. Now the repository does."""
    session = world["session"]
    repo = ScholarshipRepository(session)

    repo.save(_scholarship(world))
    second = repo.save(_scholarship(world, name=VARIANT_NAME))

    assert _rows_created(world).count() == 1
    assert second.identity_key is not None


def test_mapper_output_is_deduplicated_on_the_way_in(world):
    """The entity the mapper builds already carries identity before it is saved."""
    from services.ingestion.extractor import ExtractedScholarship

    session = world["session"]
    repo = ScholarshipRepository(session)
    extracted = ExtractedScholarship(
        scholarship_name=BASE_NAME,
        provider_name="Wrenfield Trust",
        country="Japan",
        degree="Master",
        funding_type="Fully Funded",
        application_url="https://identity.example.org/apply",
        official_source="https://identity.example.org/award",
        eligibility={},
        benefits={},
        timeline={},
        field_of_study=["Maritime Studies"],
    )
    first = repo.save(
        ScholarshipMapper(session).to_orm(
            extracted=extracted, source_id=str(world["source"].source_id)
        )
    )
    second = repo.save(
        ScholarshipMapper(session).to_orm(
            extracted=extracted.model_copy(update={"scholarship_name": VARIANT_NAME}),
            source_id=str(world["source"].source_id),
        )
    )

    assert second.scholarship_id == first.scholarship_id
    assert _rows_created(world).count() == 1


# --- cross-country split is reported, never silently merged ---------------


def test_one_scholarship_found_from_two_countries_is_flagged_not_merged(world):
    """The conflation the brief asks about: country as scope, not destination."""
    from services.scholarship.identity import detect_cross_country_clones

    session = world["session"]
    repo = ScholarshipRepository(session)
    other = session.query(Country).filter(Country.iso2 == "GB").first()

    repo.save(_scholarship(world, name=BASE_NAME))
    repo.save(
        _scholarship(
            world, name=BASE_NAME, country_id=other.country_id
        )
    )

    # Two rows: the data cannot say which country is the real destination.
    assert _rows_created(world).count() == 2
    clones = detect_cross_country_clones(session)
    assert len(clones) == 1
    assert clones[0][0] == BASE_NAME.casefold()
