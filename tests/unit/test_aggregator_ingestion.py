from types import SimpleNamespace

from services.aggregator_discovery.ingestion import _merge_verified_fields, _opportunity_names_agree
from services.ingestion.extractor import (
    Benefits,
    Eligibility,
    ExtractedScholarship,
    Timeline,
)


def test_merge_prefers_official_facts_and_keeps_field_level_evidence_and_conflicts():
    article = ExtractedScholarship(
        scholarship_name="Example Award 2027",
        provider_name="Example Foundation",
        country="France",
        official_source="https://foundation.example/about-award",
        timeline=Timeline(application_deadline="2027-01-01", application_cycle="2027"),
        eligibility=Eligibility(minimum_ielts=6.0),
        benefits=Benefits(tuition_fee=True),
    )
    official = ExtractedScholarship(
        scholarship_name="Example Award",
        provider_name="Example Foundation",
        country="France",
        timeline=Timeline(application_deadline="2027-02-01"),
        eligibility=Eligibility(minimum_ielts=6.5),
        benefits=Benefits(monthly_allowance=True),
    )

    merged, conflicts = _merge_verified_fields(
        article,
        official,
        "https://fullyscholarships.com/example-award-2027/",
        "https://foundation.example/about-award",
        "article-doc",
        "official-doc",
        SimpleNamespace(name="France"),
    )

    assert merged.scholarship_name == "Example Award"
    assert merged.timeline.application_deadline == "2027-02-01"
    assert merged.eligibility.minimum_ielts == 6.5
    assert merged.benefits.tuition_fee is True
    assert merged.benefits.monthly_allowance is True
    assert merged.extraction_meta["field_evidence"]["scholarship_name"]["document_id"] == "official-doc"
    assert merged.extraction_meta["field_evidence"]["timeline"]["application_deadline"]["source_url"] == (
        "https://foundation.example/about-award"
    )
    assert any(item["field"] == "application_deadline" for item in conflicts)
    assert any(item["field"] == "minimum_ielts" for item in conflicts)


def test_official_page_must_name_the_same_opportunity():
    assert _opportunity_names_agree("Eiffel Excellence Scholarship 2027", "Eiffel Excellence Award")
    assert not _opportunity_names_agree("Eiffel Excellence Scholarship", "Global Leaders Fellowship")
    assert not _opportunity_names_agree("Eiffel Scholarship", None)
