"""The review CLI must go through ReviewService, not around it."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from scripts.review_queue import main


@pytest.fixture
def session(rollback_session):
    return rollback_session


def _make_pending(session, *, name: str, url: str) -> Scholarship:
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    token = uuid.uuid4().hex[:8]
    base = f"https://www.chevening.org/{token}/"
    provider = Provider(
        provider_code=f"REV_{uuid.uuid4().hex[:8].upper()}",
        provider_name="Chevening Review Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Chevening Review Source",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url=base,
        crawl_entry_url=base,
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add_all([provider, source])
    session.flush()

    scholarship = Scholarship(
        scholarship_name=name,
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Computer Science"],
        official_page_url=url,
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="pending_review",
        identity_key=uuid.uuid4().hex,
        provenance_origin="exploration",
        extraction_confidence=0.9,
        requirement=ScholarshipRequirement(minimum_gpa=3.0, minimum_ielts=6.5),
        timeline=ScholarshipTimeline(
            application_open=date.today() - timedelta(days=10),
            application_deadline=date.today() + timedelta(days=180),
            application_cycle="2027",
        ),
    )
    session.add(scholarship)
    session.flush()
    return scholarship


class TestList:
    def test_list_shows_the_pending_record(self, session, capsys):
        record = _make_pending(
            session,
            name="Chevening Review CLI Scholarship 2027",
            url="https://www.chevening.org/scholarships/review-cli/",
        )

        code = main(["list", "--state", "pending_review"], session=session)

        out = capsys.readouterr().out
        assert code == 0
        assert "Chevening Review CLI Scholarship 2027" in out
        assert str(record.scholarship_id)[:8] in out

    def test_json_output_is_machine_readable(self, session, capsys):
        _make_pending(
            session,
            name="Chevening JSON Scholarship 2027",
            url="https://www.chevening.org/scholarships/json/",
        )

        code = main(["list", "--json"], session=session)

        out = capsys.readouterr().out
        assert code == 0
        assert '"scholarship_name": "Chevening JSON Scholarship 2027"' in out


class TestSummary:
    def test_summary_reports_counts(self, session, capsys):
        _make_pending(
            session,
            name="Chevening Summary Scholarship 2027",
            url="https://www.chevening.org/scholarships/summary/",
        )

        code = main(["summary"], session=session)

        out = capsys.readouterr().out
        assert code == 0
        assert "Pending review:" in out
        assert "Oldest pending:" in out


class TestApprove:
    def test_it_refuses_without_yes(self, session, capsys):
        record = _make_pending(
            session,
            name="Chevening No Yes Scholarship 2027",
            url="https://www.chevening.org/scholarships/no-yes/",
        )

        code = main(["approve", str(record.scholarship_id)], session=session)

        session.refresh(record)
        assert code == 2
        assert record.extraction_status == "pending_review"
        assert "without --yes" in capsys.readouterr().err

    def test_approval_publishes_and_audits(self, session):
        record = _make_pending(
            session,
            name="Chevening Approve Scholarship 2027",
            url="https://www.chevening.org/scholarships/approve/",
        )

        code = main(
            [
                "--actor",
                "reviewer-cli",
                "approve",
                str(record.scholarship_id),
                "--reason",
                "verified against the official page",
                "--yes",
            ],
            session=session,
        )

        session.refresh(record)
        assert code == 0
        assert record.extraction_status == "approved"
        actions = (
            session.query(ScholarshipReviewAction)
            .filter(ScholarshipReviewAction.scholarship_id == record.scholarship_id)
            .all()
        )
        assert [a.action for a in actions] == ["approved"]
        assert actions[0].actor == "reviewer-cli"


class TestReject:
    def test_rejection_requires_a_reason(self, session):
        record = _make_pending(
            session,
            name="Chevening Reject Scholarship 2027",
            url="https://www.chevening.org/scholarships/reject/",
        )

        with pytest.raises(SystemExit):
            main(["reject", str(record.scholarship_id), "--yes"], session=session)

    def test_rejection_is_recorded(self, session):
        record = _make_pending(
            session,
            name="Chevening Rejected Scholarship 2027",
            url="https://www.chevening.org/scholarships/rejected/",
        )

        code = main(
            [
                "--actor",
                "reviewer-cli",
                "reject",
                str(record.scholarship_id),
                "--reason",
                "index page, not one programme",
                "--yes",
            ],
            session=session,
        )

        session.refresh(record)
        assert code == 0
        assert record.extraction_status == "rejected"
        actions = (
            session.query(ScholarshipReviewAction)
            .filter(ScholarshipReviewAction.scholarship_id == record.scholarship_id)
            .all()
        )
        assert [a.action for a in actions] == ["rejected"]
