"""The identity backfill migration.

Two properties matter more than the fill itself:

* it **deletes nothing** — the earlier backfill (``e1a2b3c4d5f6``) resolved a
  collision by deleting a row, which is a curation decision disguised as a
  schema one;
* it is **reversible** — ``downgrade`` returns the rows this migration wrote
  to the key the previous migration's normalisation would have produced.

The migration runs inside a transaction that is rolled back afterwards, so
the shared development database is untouched.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.scholarship.identity import scholarship_identity_key

pytestmark = pytest.mark.integration

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "a4c7e91b2d05_backfill_canonical_scholarship_identity.py"
)

BASE_NAME = "Tidewater Field Studies Bursary"
VARIANT_NAME = "TIDEWATER   Field Studies Bursary!"


def _load_migration():
    spec = importlib.util.spec_from_file_location("identity_backfill_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration(rollback_session, monkeypatch):
    """Run the migration's own ``upgrade``/``downgrade`` against a rolled-back DB."""
    from alembic import op

    module = _load_migration()
    connection = rollback_session.connection()
    monkeypatch.setattr(op, "get_bind", lambda *a, **k: connection)
    return module


@pytest.fixture
def world(rollback_session):
    session = rollback_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code="XYZ_BACKFILL",
        provider_name="Tidewater Trust",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://backfill.example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Tidewater Backfill Source",
        country_id=country.country_id,
        official_url="https://backfill.example.org/",
        crawl_entry_url="https://backfill.example.org/bursary",
        crawl_method="listing",
        connector_name="generic_playwright",
        crawl_frequency="weekly",
        status="Active",
        verification_state="verified",
    )
    session.add_all([provider, source])
    session.flush()
    return {"session": session, "provider": provider, "country": country, "source": source}


def _row(world, name, *, identity=None, status="approved"):
    row = Scholarship(
        scholarship_name=name,
        provider_id=world["provider"].provider_id,
        country_id=world["country"].country_id,
        source_id=world["source"].source_id,
        official_page_url="https://backfill.example.org/bursary",
        extraction_status=status,
        field_of_study=[],
        identity_key=identity,
    )
    world["session"].add(row)
    world["session"].flush()
    return row


def _legacy_key(world, name=BASE_NAME):
    """The key ``e1a2b3c4d5f6`` would have written for this row."""
    import hashlib
    import re

    normalized = re.sub(r"\s+", " ", name.strip().lower())
    payload = "|".join(
        [str(world["provider"].provider_id), normalized, str(world["country"].country_id)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rows(world):
    return (
        world["session"]
        .query(Scholarship)
        .filter(Scholarship.source_id == world["source"].source_id)
        .all()
    )


# --- upgrade ---------------------------------------------------------------


def test_upgrade_fills_a_null_identity(world, migration):
    row = _row(world, BASE_NAME)
    assert row.identity_key is None

    migration.upgrade()

    world["session"].refresh(row)
    assert row.identity_key == scholarship_identity_key(
        row.provider_id, row.scholarship_name, row.country_id
    )


def test_upgrade_leaves_an_existing_identity_untouched(world, migration):
    """A key the earlier migration wrote keeps its value."""
    legacy = _legacy_key(world)
    row = _row(world, BASE_NAME, identity=legacy)

    migration.upgrade()

    world["session"].refresh(row)
    assert row.identity_key == legacy


def test_upgrade_does_not_delete_a_colliding_row(world, migration):
    """The rule the previous migration broke: a collision is reported, not resolved."""
    first = _row(world, BASE_NAME, status="approved")
    # Same provider, same country, a name that canonicalises identically.
    second = _row(world, VARIANT_NAME, status="rejected")

    migration.upgrade()

    world["session"].refresh(first)
    world["session"].refresh(second)
    surviving = _rows(world)
    assert len(surviving) == 2
    assert {r.scholarship_id for r in surviving} == {first.scholarship_id, second.scholarship_id}
    keys = [r.identity_key for r in surviving]
    # Exactly one row owns the identity; the other stays visible as NULL.
    assert keys.count(None) == 1
    assert len([k for k in keys if k]) == 1


def test_upgrade_leaves_no_row_deleted_whatever_the_data(world, migration):
    rows = [_row(world, f"Tidewater Award {i}") for i in range(5)]
    before = {r.scholarship_id for r in rows}

    migration.upgrade()

    assert {r.scholarship_id for r in _rows(world)} == before


def test_upgrade_is_idempotent(world, migration):
    _row(world, BASE_NAME)

    migration.upgrade()
    first_key = _rows(world)[0].identity_key
    migration.upgrade()

    assert _rows(world)[0].identity_key == first_key


# --- downgrade -------------------------------------------------------------


def test_downgrade_restores_the_previous_key_form(world, migration):
    row = _row(world, BASE_NAME)
    migration.upgrade()
    world["session"].refresh(row)
    assert row.identity_key is not None

    migration.downgrade()
    world["session"].refresh(row)

    assert row.identity_key == _legacy_key(world)


def test_upgrade_then_downgrade_loses_no_rows(world, migration):
    rows = [_row(world, f"Tidewater Award {i}") for i in range(4)]
    before = {r.scholarship_id for r in rows}

    migration.upgrade()
    migration.downgrade()

    assert {r.scholarship_id for r in _rows(world)} == before


def test_the_migration_file_exists_at_the_path_alembic_reads():
    assert MIGRATION_PATH.exists()


# --- the shape of the migration chain -------------------------------------


def test_migration_has_exactly_one_head():
    """A wrong ``down_revision`` silently forks the chain into two heads."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    lines = [line for line in result.stdout.splitlines() if "(head)" in line]
    assert len(lines) == 1, f"expected one migration head, found {lines}"


def test_migration_revisions_are_unique_across_the_tree():
    import re as _re

    versions = MIGRATION_PATH.parent.glob("*.py")
    revisions = []
    for path in versions:
        text = path.read_text(encoding="utf-8")
        match = _re.search(r'^revision(?:\s*:\s*str)?\s*=\s*["\']([0-9a-zA-Z_]+)["\']', text, _re.M)
        if match:
            revisions.append((match.group(1), path.name))

    ids = [rev for rev, _ in revisions]
    assert len(ids) == len(set(ids)), "duplicate revision id in the migration tree"
