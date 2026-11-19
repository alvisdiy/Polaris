"""Unit tests for ScholarshipRepository."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from database.models.scholarship import Scholarship
from services.scholarship.identity import (
    IdentityUnavailable,
    scholarship_identity_key,
)
from services.scholarship.repository import ScholarshipRepository

pytestmark = pytest.mark.unit


def _mock_scholarship(**overrides) -> MagicMock:
    s = MagicMock(spec=Scholarship)
    # None by default, matching a transient entity: the mapper builds a
    # Scholarship and hands it to save() before the UUID default is applied at
    # flush time. Tests that need an id pass one explicitly.
    s.scholarship_id = overrides.get("scholarship_id")
    s.scholarship_name = overrides.get("scholarship_name", "Test Scholarship")
    s.provider_id = overrides.get("provider_id", uuid.uuid4())
    s.country_id = overrides.get("country_id", uuid.uuid4())
    s.source_id = overrides.get("source_id", uuid.uuid4())
    s.degree = overrides.get("degree", "Master")
    s.funding_type = overrides.get("funding_type", "Fully Funded")
    s.field_of_study = overrides.get("field_of_study", ["CS"])
    s.extraction_status = overrides.get("extraction_status", "approved")
    return s


# --- save ---


def _no_existing_identity(session: MagicMock) -> MagicMock:
    """Mock a session where this identity has not been seen before.

    ``save`` now asks the database whether the canonical identity already
    exists. A bare ``MagicMock`` answers with a truthy object, which would
    make every save take the duplicate branch.
    """
    session.query.return_value.filter.return_value.first.return_value = None
    return session


def test_save():
    session = _no_existing_identity(MagicMock())
    repo = ScholarshipRepository(session)
    scholarship = _mock_scholarship()

    result = repo.save(scholarship)

    session.add.assert_called_once_with(scholarship)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(scholarship)
    assert result is scholarship


def test_save_assigns_canonical_identity_key():
    """Identity is derived by the repository, not supplied by the caller.

    This is the invariant: an acquisition path that forgets to set the key
    still lands inside deduplication.
    """
    session = _no_existing_identity(MagicMock())
    repo = ScholarshipRepository(session)
    scholarship = _mock_scholarship(scholarship_name="  Global   Excellence Scholarship ")
    scholarship.identity_key = None

    repo.save(scholarship)

    assert scholarship.identity_key == scholarship_identity_key(
        scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
    )


def test_save_returns_existing_row_instead_of_inserting_a_duplicate():
    """A second extraction of the same scholarship must not add a row."""
    session = MagicMock()
    canonical = _mock_scholarship(scholarship_name="Global Excellence Scholarship")
    session.query.return_value.filter.return_value.first.return_value = canonical
    repo = ScholarshipRepository(session)
    duplicate = _mock_scholarship(
        provider_id=canonical.provider_id,
        country_id=canonical.country_id,
        scholarship_name="GLOBAL  EXCELLENCE   SCHOLARSHIP!",
    )

    result = repo.save(duplicate)

    assert result is canonical
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_save_does_not_overwrite_an_approved_row_with_a_rejected_one():
    """Dedup never writes: an approved record cannot be downgraded."""
    session = MagicMock()
    approved = _mock_scholarship(extraction_status="approved")
    session.query.return_value.filter.return_value.first.return_value = approved
    repo = ScholarshipRepository(session)
    rejected = _mock_scholarship(
        provider_id=approved.provider_id,
        country_id=approved.country_id,
        extraction_status="rejected",
    )

    result = repo.save(rejected)

    assert result.extraction_status == "approved"
    session.commit.assert_not_called()


def test_save_refuses_a_row_with_no_usable_name():
    """A row with no derivable identity would be permanently outside dedup."""
    session = _no_existing_identity(MagicMock())
    repo = ScholarshipRepository(session)

    with pytest.raises(IdentityUnavailable):
        repo.save(_mock_scholarship(scholarship_name="   "))

    session.add.assert_not_called()


# --- get_by_id ---


def test_get_by_id():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    sid = uuid.uuid4()
    expected = _mock_scholarship(scholarship_id=sid)

    session.query.return_value.options.return_value.filter.return_value.first.return_value = expected

    result = repo.get_by_id(sid)
    assert result is expected


def test_get_by_id_not_found():
    session = MagicMock()
    repo = ScholarshipRepository(session)

    session.query.return_value.options.return_value.filter.return_value.first.return_value = None

    result = repo.get_by_id(uuid.uuid4())
    assert result is None


# --- get_all_approved ---


def test_get_all_approved():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    scholarships = [_mock_scholarship(), _mock_scholarship()]

    session.query.return_value.options.return_value.filter.return_value.all.return_value = scholarships

    result = repo.get_all_approved()
    assert len(result) == 2


def test_get_all_approved_empty():
    session = MagicMock()
    repo = ScholarshipRepository(session)

    session.query.return_value.options.return_value.filter.return_value.all.return_value = []

    result = repo.get_all_approved()
    assert result == []


# --- find_duplicate ---


def test_find_duplicate_found():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    expected = _mock_scholarship()

    session.query.return_value.filter.return_value.join.return_value.filter.return_value.first.return_value = expected

    result = repo.find_duplicate(
        scholarship_name="Test",
        provider_id=uuid.uuid4(),
        application_cycle="2025",
        source_id=uuid.uuid4(),
    )
    assert result is expected


def test_find_duplicate_not_found():
    session = MagicMock()
    repo = ScholarshipRepository(session)

    session.query.return_value.filter.return_value.join.return_value.filter.return_value.first.return_value = None

    result = repo.find_duplicate(
        scholarship_name="Test",
        provider_id=uuid.uuid4(),
        application_cycle="2025",
        source_id=uuid.uuid4(),
    )
    assert result is None


def test_find_duplicate_null_cycle():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    expected = _mock_scholarship()

    session.query.return_value.filter.return_value.join.return_value.filter.return_value.first.return_value = expected

    result = repo.find_duplicate(
        scholarship_name="Test",
        provider_id=uuid.uuid4(),
        application_cycle=None,
        source_id=uuid.uuid4(),
    )
    assert result is expected


# --- update ---


def test_update():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    scholarship = _mock_scholarship()

    result = repo.update(scholarship)

    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(scholarship)
    assert result is scholarship
