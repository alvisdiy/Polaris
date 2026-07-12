"""Unit tests for ScholarshipRepository."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from database.models.scholarship import Scholarship
from services.scholarship.repository import ScholarshipRepository

pytestmark = pytest.mark.unit


def _mock_scholarship(**overrides) -> MagicMock:
    s = MagicMock(spec=Scholarship)
    s.scholarship_id = overrides.get("scholarship_id", uuid.uuid4())
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


def test_save():
    session = MagicMock()
    repo = ScholarshipRepository(session)
    scholarship = _mock_scholarship()

    result = repo.save(scholarship)

    session.add.assert_called_once_with(scholarship)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(scholarship)
    assert result is scholarship


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
