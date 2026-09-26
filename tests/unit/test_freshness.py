"""Unit tests: deadline freshness classification (Phase C semantics)."""

from datetime import date, timedelta

import pytest

from services.scholarship.freshness import (
    STATE_ACTIVE,
    STATE_EXPIRED,
    STATE_ROLLING,
    STATE_UNKNOWN,
    classify_deadline,
    condense_observations,
    detect_rolling,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 26)


class TestClassifyDeadline:
    def test_future_deadline_is_active(self):
        assert classify_deadline(TODAY + timedelta(days=30), today=TODAY) == STATE_ACTIVE

    def test_today_deadline_is_active(self):
        assert classify_deadline(TODAY, today=TODAY) == STATE_ACTIVE

    def test_past_deadline_is_expired(self):
        assert classify_deadline(TODAY - timedelta(days=1), today=TODAY) == STATE_EXPIRED

    def test_missing_deadline_is_unknown_never_invented(self):
        assert classify_deadline(None, today=TODAY) == STATE_UNKNOWN

    def test_rolling_phrases_beat_extracted_dates(self):
        """'until all positions are filled' is not a deadline — even if a
        heuristic date also appeared on the page."""
        for text in (
            "Applications accepted until all positions are filled. Deadline: May 1, 2020",
            "Rolling admissions basis for international applicants",
            "This program is open year-round",
            "There is no application deadline for this bursary",
        ):
            assert classify_deadline(TODAY - timedelta(days=365), page_text=text, today=TODAY) == STATE_ROLLING

    def test_rolling_detection_is_case_insensitive(self):
        assert detect_rolling("OPEN UNTIL ALL POSITIONS ARE FILLED")

    def test_ordinary_deadline_text_is_not_rolling(self):
        assert not detect_rolling("Application deadline: March 1, 2027")


class TestCondenseObservations:
    def test_groups_by_url_and_counts(self):
        obs = [
            {"url": "https://a.example/x", "at": "2026-01-01", "rank": 1},
            {"url": "https://a.example/x", "at": "2026-02-01", "rank": 3},
            {"url": "https://b.example/y", "at": "2026-03-01", "rank": 2},
        ]
        result = condense_observations(obs)
        entries = {e["url"]: e for e in result["observations"]}
        assert result["total_condensed"] == 2
        assert entries["https://a.example/x"]["times_seen"] == 2
        assert entries["https://a.example/x"]["first_seen"] == "2026-01-01"
        assert entries["https://a.example/x"]["last_seen"] == "2026-02-01"

    def test_respects_limit(self):
        obs = [{"url": f"https://e{i}.example/", "at": "2026-01-01"} for i in range(30)]
        result = condense_observations(obs, limit=5)
        assert len(result["observations"]) == 5
        assert result["total_condensed"] == 30

    def test_empty_input(self):
        assert condense_observations([])["observations"] == []
        assert condense_observations(None)["observations"] == []
