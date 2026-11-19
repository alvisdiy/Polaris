"""Priority D — a page that contradicts itself about its own deadline.

M10 recorded the behaviour as "effectively first-match": the extractor
returned the first deadline the page stated and discarded the rest. On a page
that says "applications close 15 January" and then "deadline extended to 31
January", that is a guess presented as a fact, and it is the guess that makes
a student apply late.

Polaris already had a conflict mechanism for cross-source disagreement
(``scholarship.conflicts`` → ``CONFLICTING`` → routes to review). Nothing
wrote it. These tests pin the extension: the shape is unchanged, only its
origin is new.
"""

from __future__ import annotations

import pytest

from services.ingestion.real_extractor import DeterministicLLMClient

# Realistic page fixtures, not synthetic one-liners: the point is that a real
# page contradicts itself in prose, with surrounding text that must not be
# mistaken for a second deadline.

CONTRADICTING_PAGE = """
Important dates

Applications close 15 January 2027. Applicants must submit all documents by
this date.

Eligibility and selection

The application deadline is 31 January 2027. Late submissions cannot be
accepted.
"""

RESOLVED_PAGE = """
Important dates

Applications close 15 January 2027.

Update: the application deadline has been extended to 31 January 2027.
"""

# A page that states several different dates but none of them as the deadline.
UNRELATED_DATES_PAGE = """
The award was established in 2019 and the first recipients were enrolled in
September 2020. Applications close 15 January 2027.
Interview rounds take place in March 2027 and results are announced in April
2027.
"""

SINGLE_DATE_PAGE = "Applications close 15 January 2027 and results follow in April."


def _extract(text: str) -> dict:
    client = DeterministicLLMClient()
    payload = client.extract_scholarship(
        clean_text=text,
        source_url="https://example.edu/awards/some-scholarship",
        page_title="Some Scholarship",
    )
    return payload


class TestThePageContradictingItself:
    def test_a_superseded_deadline_is_taken(self):
        """The page says the deadline moved; the moved date is the operative one."""
        result = _extract(RESOLVED_PAGE)
        assert result["timeline"]["application_deadline"] == "2027-01-31"

    def test_the_superseded_date_is_kept_as_evidence(self):
        result = _extract(RESOLVED_PAGE)
        conflict = result["_extraction"]["deadline_conflict"]
        values = {v["value"] for v in conflict["values"]}
        assert values == {"2027-01-15", "2027-01-31"}
        assert conflict["resolved"] is True

    def test_the_evidence_quotes_the_page(self):
        """A conflict a reviewer cannot check is not evidence."""
        result = _extract(RESOLVED_PAGE)
        conflict = result["_extraction"]["deadline_conflict"]
        sentences = " ".join(v["sentence"] for v in conflict["values"])
        assert "extended to 31 January 2027" in sentences


class TestTwoDeadlinesAndNoResolution:
    """The M10 failure. First-match is not an answer when the page disagrees."""

    def test_no_deadline_is_stored_when_the_page_does_not_settle_it(self):
        result = _extract(CONTRADICTING_PAGE)
        assert result["timeline"]["application_deadline"] is None, (
            "storing either date would pick a side of a disagreement the page "
            "never settled"
        )

    def test_the_contradiction_is_reported(self):
        result = _extract(CONTRADICTING_PAGE)
        conflict = result["_extraction"]["deadline_conflict"]
        assert conflict is not None
        assert conflict["resolved"] is False
        assert {v["value"] for v in conflict["values"]} == {
            "2027-01-15",
            "2027-01-31",
        }

    def test_the_report_says_the_page_disagrees_with_itself(self):
        conflict = _extract(CONTRADICTING_PAGE)["_extraction"]["deadline_conflict"]
        assert "different" in conflict["reason"]

    def test_a_page_that_says_nothing_of_the_sort_is_left_alone(self):
        """A single deadline stated twice in two formats is not a conflict."""
        page = (
            "The application deadline is 15 January 2027. "
            "Applications close 15 January 2027."
        )
        result = _extract(page)
        assert result["_extraction"]["deadline_conflict"] is None
        assert result["timeline"]["application_deadline"] == "2027-01-15"


class TestNoContradictionIsInvented:
    """The detector must not turn ordinary prose about other dates into a conflict."""

    def test_other_dates_on_the_page_are_not_deadlines(self):
        result = _extract(UNRELATED_DATES_PAGE)
        assert result["_extraction"]["deadline_conflict"] is None
        assert result["timeline"]["application_deadline"] == "2027-01-15"

    def test_a_page_with_one_deadline_is_untouched(self):
        result = _extract(SINGLE_DATE_PAGE)
        assert result["_extraction"]["deadline_conflict"] is None
        assert result["timeline"]["application_deadline"] == "2027-01-15"

    def test_a_page_with_no_deadline_is_untouched(self):
        result = _extract("The award supports students from any country.")
        assert result["_extraction"]["deadline_conflict"] is None
        assert result["timeline"]["application_deadline"] is None


@pytest.mark.data
class TestItFeedsTheExistingConflictMechanism:
    """No new subsystem: the shape `quality._conflict_map` reads is the one used."""

    @pytest.fixture
    def mapped(self, session):
        from database.models.country import Country
        from database.models.provider import Provider
        from database.models.source_registry import SourceRegistry
        from services.ingestion.extractor import ExtractedScholarship
        from services.scholarship.mapper import ScholarshipMapper

        country = session.query(Country).first()
        provider = session.query(Provider).first()
        source = session.query(SourceRegistry).first()
        if not all([country, provider, source]):
            pytest.skip("prerequisite seed data missing")

        payload = _extract(CONTRADICTING_PAGE)
        meta = payload.pop("_extraction")
        meta["document_id"] = str(source.source_id)
        meta["origin"] = "exploration"
        result = ExtractedScholarship(**payload).model_copy(
            update={"extraction_meta": meta}
        )
        scholarship = ScholarshipMapper(session).to_orm(result, str(source.source_id))
        session.flush()
        yield scholarship
        session.expunge_all()

    def test_the_unresolved_conflict_reaches_the_record(self, mapped):
        conflicts = mapped.conflicts or []
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "application_deadline"

    def test_each_side_carries_its_url_and_its_sentence(self, mapped):
        for value in mapped.conflicts[0]["values"]:
            assert value["source_url"] == "https://example.edu/awards/some-scholarship"
            assert value["sentence"]

    def test_the_quality_gate_reads_it_as_conflicting(self, mapped):
        """The point of writing to `conflicts`: the field stops being settled."""
        from services.review.quality import FieldQuality, build_report

        report = build_report(
            scholarship_name=mapped.scholarship_name,
            name_verdict=(mapped.field_provenance or {}).get("name_verdict"),
            provider_name=mapped.provider.provider_name if mapped.provider else None,
            country_name=mapped.country.name if mapped.country else None,
            official_page_url=mapped.official_page_url,
            degree=mapped.degree,
            funding_type=mapped.funding_type,
            field_of_study=list(mapped.field_of_study or []),
            deadline_present=mapped.timeline is not None,
            application_deadline=(
                mapped.timeline.application_deadline if mapped.timeline else None
            ),
            conflicts=mapped.conflicts,
        )
        assert report.fields["application_deadline"].quality == FieldQuality.CONFLICTING

    def test_a_conflicting_deadline_is_not_publishable_on_its_own(self, mapped):
        """Deadline is optional, so this is about visibility, not the gate.

        The record stays reviewable and the reviewer sees the disagreement;
        what must not happen is the field being presented as settled.
        """
        from services.review.quality import _conflict_map

        cmap = _conflict_map(mapped.conflicts)
        assert cmap["application_deadline"]


@pytest.mark.data
class TestAResolvedConflictIsNotAConflict:
    def test_it_does_not_block_publication(self, session):
        from database.models.country import Country
        from database.models.provider import Provider
        from database.models.source_registry import SourceRegistry
        from services.ingestion.extractor import ExtractedScholarship
        from services.review.quality import FieldQuality, build_report
        from services.scholarship.mapper import ScholarshipMapper

        country = session.query(Country).first()
        provider = session.query(Provider).first()
        source = session.query(SourceRegistry).first()
        if not all([country, provider, source]):
            pytest.skip("prerequisite seed data missing")

        payload = _extract(RESOLVED_PAGE)
        meta = payload.pop("_extraction")
        meta["document_id"] = str(source.source_id)
        meta["origin"] = "exploration"
        result = ExtractedScholarship(**payload).model_copy(
            update={"extraction_meta": meta}
        )
        scholarship = ScholarshipMapper(session).to_orm(result, str(source.source_id))
        session.flush()

        assert not scholarship.conflicts
        report = build_report(
            scholarship_name=scholarship.scholarship_name,
            name_verdict=(scholarship.field_provenance or {}).get("name_verdict"),
            provider_name=provider.provider_name,
            country_name=country.name,
            official_page_url=scholarship.official_page_url,
            degree=scholarship.degree,
            funding_type=scholarship.funding_type,
            field_of_study=list(scholarship.field_of_study or []),
            deadline_present=scholarship.timeline is not None,
            application_deadline=(
                scholarship.timeline.application_deadline if scholarship.timeline else None
            ),
            conflicts=scholarship.conflicts,
        )
        assert report.fields["application_deadline"].quality == FieldQuality.KNOWN
        # The superseded date is still visible to a reviewer.
        deadline_provenance = (scholarship.field_provenance or {})[
            "application_deadline"
        ]
        assert deadline_provenance["superseded_deadlines"]
        session.expunge_all()
