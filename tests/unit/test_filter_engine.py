"""Tests for FilterEngine (M3.2)."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from services.matching.filter import FilterEngine
from services.matching.models.profile import UserProfile

pytestmark = pytest.mark.unit


def _make_scholarship(name, degree="Master", deadline=None):
    """Create a mock scholarship with timeline."""
    sch = MagicMock()
    sch.scholarship_name = name
    sch.degree = degree
    sch.timeline = MagicMock()
    sch.timeline.application_deadline = deadline
    return sch


def _profile():
    return UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["CS"],
        current_gpa=3.5,
        research_experience="Optional",
        work_experience="Optional",
        publication="Not Required",
        leadership=False,
        funding_preference="Fully Funded",
    )


class TestFilterEngine:
    """FilterEngine mandatory filter tests."""

    def setup_method(self):
        self.engine = FilterEngine()
        self.profile = _profile()

    def test_future_deadline_passes(self):
        sch = _make_scholarship("Future", deadline=date.today() + timedelta(days=90))
        result = self.engine.filter(self.profile, [sch])
        assert len(result) == 1

    def test_expired_deadline_excluded(self):
        sch = _make_scholarship("Expired", deadline=date.today() - timedelta(days=30))
        result = self.engine.filter(self.profile, [sch])
        assert len(result) == 0

    def test_null_deadline_passes(self):
        sch = _make_scholarship("No Deadline", deadline=None)
        result = self.engine.filter(self.profile, [sch])
        assert len(result) == 1

    def test_no_timeline_passes(self):
        sch = MagicMock()
        sch.scholarship_name = "No Timeline"
        sch.timeline = None
        result = self.engine.filter(self.profile, [sch])
        assert len(result) == 1

    def test_mixed_scholarships(self):
        future = _make_scholarship("Future", deadline=date.today() + timedelta(days=90))
        expired = _make_scholarship("Expired", deadline=date.today() - timedelta(days=30))
        no_deadline = _make_scholarship("No Deadline", deadline=None)
        result = self.engine.filter(self.profile, [future, expired, no_deadline])
        names = {s.scholarship_name for s in result}
        assert "Future" in names
        assert "No Deadline" in names
        assert "Expired" not in names
