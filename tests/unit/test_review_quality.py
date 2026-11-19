"""Unit tests for the publication quality gates.

The gate's whole purpose is to stop treating "we don't know" and "the source
says nothing" as the same thing. These tests pin that distinction, the
required-versus-optional split, and conflict handling.
"""

from __future__ import annotations

from datetime import date

from services.review.quality import (
    OPTIONAL_FIELDS,
    PLACEHOLDER_SOURCE_HOSTS,
    REQUIRED_TO_PUBLISH,
    FieldQuality,
    assess_benefits,
    assess_identity,
    assess_scalar,
    build_report,
    is_placeholder_source,
    placeholder_source_host,
)


class TestScalarAssessment:
    def test_value_present_is_known(self):
        a = assess_scalar("degree", "Master")
        assert a.quality == FieldQuality.KNOWN
        assert a.value == "Master"

    def test_source_silent_is_unknown(self):
        """We read the field; the source published nothing. That is a fact."""
        a = assess_scalar("deadline", None, present=True)
        assert a.quality == FieldQuality.UNKNOWN
        assert "does not publish" in a.detail

    def test_field_not_read_is_missing(self):
        """We never got the field. That is our gap, not the source's."""
        a = assess_scalar("deadline", None, present=False)
        assert a.quality == FieldQuality.MISSING
        assert "not read" in a.detail

    def test_unknown_and_missing_are_different_states(self):
        assert (
            assess_scalar("x", None, present=True).quality
            != assess_scalar("x", None, present=False).quality
        )

    def test_blank_string_counts_as_absent(self):
        assert assess_scalar("degree", "   ").quality != FieldQuality.KNOWN

    def test_conflicting_values_are_flagged(self):
        a = assess_scalar("deadline", "2027-01-01", conflicts=["2027-01-01", "2027-02-02"])
        assert a.quality == FieldQuality.CONFLICTING
        assert "disagree" in a.detail

    def test_agreeing_sources_count_as_known_absence(self):
        a = assess_scalar("deadline", None, conflicts=[None, None])
        assert a.quality == FieldQuality.UNKNOWN


class TestIdentityAssessment:
    def test_real_name_is_known(self):
        a = assess_identity("MEXT Scholarship for Research Students")
        assert a.quality == FieldQuality.KNOWN

    def test_missing_name_is_missing_with_reason(self):
        a = assess_identity(None, name_verdict={"reasons": ["reads as a sentence"]})
        assert a.quality == FieldQuality.MISSING
        assert "reads as a sentence" in a.detail

    def test_unidentifiable_name_is_conflicting(self):
        """A name with no proper noun needs a human to confirm it."""
        a = assess_identity("Available Scholarships")
        assert a.quality == FieldQuality.CONFLICTING
        # The reason is the specific genericity finding, not a generic nudge:
        # both words name the opportunity category and nothing else.
        assert "names only the opportunity category" in a.detail

    def test_reason_is_specific_to_which_genericity_applied(self):
        """A reviewer is told what is wrong, in the extractor's own words."""
        assert "reads as a sentence" in assess_identity(
            "Applications for the 2027 intake are now open to applicants"
        ).detail
        assert "navigation/UI label" in assess_identity("At a glance").detail
        assert "explicit unknown placeholder" in assess_identity("Unknown Scholarship").detail


class TestBenefitsAssessment:
    def test_granted_benefits_are_known(self):
        a = assess_benefits({"tuition_fee": True, "accommodation": False})
        assert a.quality == FieldQuality.KNOWN
        assert a.value == ["tuition_fee"]

    def test_unread_benefits_are_missing(self):
        a = assess_benefits(None)
        assert a.quality == FieldQuality.MISSING

    def test_no_benefits_is_unknown_not_false(self):
        """Covering nothing is not the same as having read nothing."""
        a = assess_benefits({"tuition_fee": False, "accommodation": False})
        assert a.quality == FieldQuality.UNKNOWN
        assert "not the same as covering nothing" in a.detail


class TestBuildReport:
    def _report(self, **overrides):
        base = dict(
            scholarship_name="Monbukagakusho Scholarship 2027",
            name_verdict=None,
            provider_name="Ministry of Education, Japan",
            country_name="Japan",
            official_page_url="https://www.studyinjapan.go.jp/",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Engineering"],
            deadline_present=True,
            application_deadline=date(2027, 3, 1),
            application_open=None,
            application_cycle="2027",
        )
        base.update(overrides)
        return build_report(**base)

    def test_complete_record_is_publishable(self):
        report = self._report()
        assert report.publishable, report.blocking
        assert report.blocking == []

    def test_missing_identity_blocks(self):
        report = self._report(scholarship_name=None)
        assert not report.publishable
        assert "identity" in report.blocking

    def test_missing_official_source_blocks(self):
        report = self._report(official_page_url=None)
        assert not report.publishable
        assert "official_source" in report.blocking

    def test_placeholder_official_source_blocks(self):
        """The catalogue held an approved record sourced from example.com.

        A non-empty URL was the whole of the old check, and example.com is
        non-empty, so the record published. The host is what decides.
        """
        report = self._report(official_page_url="https://example.com/scholarships")
        assert not report.publishable
        assert "official_source" in report.blocking
        source = report.fields["official_source"]
        assert source.quality == FieldQuality.MISSING
        assert "example.com" in source.detail

    def test_placeholder_does_not_masquerade_as_a_present_value(self):
        """`official_page_url` must not read KNOWN while the gate refuses it."""
        report = self._report(official_page_url="https://example.com/x")
        assert report.fields["official_page_url"].quality == FieldQuality.MISSING

    def test_real_official_source_is_unaffected(self):
        """The hosts the live catalogue actually uses must all still publish."""
        for host in (
            "https://www.studyinjapan.go.jp/en/",
            "https://www.daad.de/en/studying-in-germany/scholarships/",
            "https://www.chevening.org/scholarship/",
            "https://lpdp.kemenkeu.go.id/",
            "https://www.sheffield.ac.uk/scholarships",
            "https://www.sp.edu.sg/",
        ):
            report = self._report(official_page_url=host)
            assert report.publishable, (host, report.blocking)
            assert report.fields["official_source"].quality == FieldQuality.KNOWN

    def test_missing_degree_is_reported_but_does_not_block(self):
        """Soft field: the gap is visible, the record is still publishable."""
        report = self._report(degree=None)
        assert report.publishable, report.blocking
        assert "degree" not in report.blocking
        assert report.fields["degree"].quality == "UNKNOWN"
        assert "not stated" in report.fields["degree"].detail

    def test_a_stated_set_of_levels_satisfies_the_degree_gate(self):
        # A national database that lists "Academic level: Doctoral / Master's"
        # states the award's levels; the fact is known, there are just several
        # of them. Blocking those would block most of the Japanese catalogue
        # for a gap that is not a gap.
        report = self._report(degree=None, degree_levels=["Master", "PhD"])
        assert report.publishable, report.blocking
        assert report.fields["degree"].quality == "KNOWN"

    def test_empty_level_list_is_the_same_soft_gap(self):
        report = self._report(degree=None, degree_levels=[])
        assert report.publishable
        assert report.fields["degree"].quality == "UNKNOWN"

    def test_missing_provider_or_country_blocks(self):
        assert "provider" in self._report(provider_name=None).blocking
        assert "country" in self._report(country_name=None).blocking

    def test_missing_optional_fields_do_not_block(self):
        """Real awards lack these; requiring them would reject correct data."""
        report = self._report(
            funding_type=None,
            field_of_study=[],
            application_deadline=None,
            application_open=None,
        )
        assert report.publishable, report.blocking
        assert report.fields["funding_type"].quality == FieldQuality.UNKNOWN

    def test_absent_timeline_is_a_missing_deadline_not_unknown(self):
        report = self._report(deadline_present=False, application_deadline=None)
        assert report.fields["deadline"].quality == FieldQuality.MISSING

    def test_conflict_blocks_and_is_reported(self):
        report = self._report(
            conflicts=[
                {
                    "field": "application_deadline",
                    "values": [
                        {"source_url": "https://a.example", "value": "2027-03-01"},
                        {"source_url": "https://b.example", "value": "2027-04-15"},
                    ],
                }
            ]
        )
        assert not report.publishable
        assert "application_deadline" in report.conflicting
        assert report.fields["deadline"].quality == FieldQuality.CONFLICTING

    def test_conflict_on_an_unassessed_field_still_blocks(self):
        report = self._report(
            conflicts=[{"field": "age_limit", "values": [20, 25]}]
        )
        assert "age_limit" in report.conflicting
        assert not report.publishable

    def test_report_is_json_serialisable(self):
        report = self._report()
        payload = report.to_dict()
        assert isinstance(payload["fields"]["identity"]["value"], str)
        assert "publishable" in payload

    def test_required_and_optional_sets_are_disjoint(self):
        assert not (set(REQUIRED_TO_PUBLISH) & set(OPTIONAL_FIELDS))

    def test_optional_fields_cover_the_api_contract(self):
        """Every nullable field in the API contract must be classified."""
        for name in ("funding_type", "deadline", "field_of_study"):
            assert name in OPTIONAL_FIELDS


class TestPlaceholderSourceHost:
    """The rule is reserved names only, so it cannot reject a real provider."""

    def test_reserved_example_hosts_are_placeholders(self):
        for url in (
            "https://example.com/scholarships",
            "http://example.com",
            "https://www.example.com/awards",
            "https://example.net/",
            "https://example.org/page",
            "https://sub.example.com/deep/path",
        ):
            assert placeholder_source_host(url), url

    def test_localhost_forms_are_placeholders(self):
        for url in (
            "http://localhost",
            "http://localhost:8000/api/v1/scholarships",
            "https://app.localhost/",
            "http://127.0.0.1:3000/",
            "http://0.0.0.0/",
            "http://[::1]:8080/",
        ):
            assert placeholder_source_host(url), url

    def test_reserved_tlds_are_placeholders(self):
        for url in (
            "https://scholarship.test/",
            "https://example.invalid/award",
            "https://department.example/",
        ):
            assert placeholder_source_host(url), url

    def test_a_bare_host_is_recognised_without_a_scheme(self):
        """A reviewer typing a host into the correction box gets the verdict."""
        assert placeholder_source_host("example.com") == "example.com"
        assert placeholder_source_host("example.com/apply") == "example.com"
        assert is_placeholder_source("localhost")

    def test_the_offending_host_is_named(self):
        assert placeholder_source_host("https://www.example.com/x") == "www.example.com"

    def test_empty_input_is_not_a_placeholder(self):
        """Absence is the existing MISSING path, not this rule's business."""
        for value in (None, "", "   "):
            assert placeholder_source_host(value) is None

    def test_real_domains_are_not_rejected(self):
        """Narrow on purpose: an unfamiliar host is not a placeholder.

        Each of these is either a domain from the live catalogue or a host that
        merely contains a reserved word, and rejecting any of them would break a
        legitimate provider.
        """
        for url in (
            "https://www.studyinjapan.go.jp/en/",
            "https://www2.daad.de/deutschland/stipendium/",
            "https://lpdp.kemenkeu.go.id/beasiswa/",
            "https://www.lboro.ac.uk/study/postgraduate/funding/",
            # contains "example" but is not a reserved name
            "https://exampleuniversity.edu/scholarships",
            "https://www.myexample.org/award",
            "https://notexample.com/",
            "https://examplescholarships.ac.uk/",
            # contains "test" but is a real host shape
            "https://testimonials.university.edu/",
            # a plain wrong-but-real path is not this rule's concern
            "/scholarships/local",
        ):
            assert placeholder_source_host(url) is None, url

    def test_the_reserved_set_matches_the_module_constant(self):
        assert PLACEHOLDER_SOURCE_HOSTS == {
            "example.com", "example.net", "example.org", "localhost",
        }


class TestReportSerialisation:
    def test_field_assessment_to_dict_has_detail(self):
        a = assess_scalar("x", None, present=False)
        assert set(a.to_dict()) == {"field", "quality", "value", "detail"}


class TestBenefitsFromOrmRow:
    """Regression: an ORM row must not report its own internals as benefits.

    Reading a SQLAlchemy instance's __dict__ yields _sa_instance_state, which
    is truthy, so a benefits row granting nothing looked like it granted
    something. Caught against real data from a live SG exploration run.
    """

    def test_orm_row_with_no_grants_reports_no_granted_benefits(self):
        from database.models.scholarship_benefit import ScholarshipBenefit

        row = ScholarshipBenefit(
            tuition_fee=False, monthly_allowance=False, accommodation=False,
            health_insurance=False, travel_ticket=False, research_grant=False,
        )
        assessment = assess_benefits(row)
        assert assessment.value == []
        assert all(not k.startswith("_") for k in assessment.value)
        assert "_sa_instance_state" not in str(assessment.value)

    def test_orm_row_reports_only_real_benefits(self):
        from database.models.scholarship_benefit import ScholarshipBenefit

        row = ScholarshipBenefit(
            tuition_fee=True, monthly_allowance=True, accommodation=False,
            health_insurance=False, travel_ticket=True, research_grant=False,
        )
        assessment = assess_benefits(row)
        assert assessment.quality == FieldQuality.KNOWN
        assert assessment.value == ["monthly_allowance", "travel_ticket", "tuition_fee"]

    def test_dict_input_still_works(self):
        assessment = assess_benefits({"tuition_fee": True, "accommodation": False})
        assert assessment.value == ["tuition_fee"]
