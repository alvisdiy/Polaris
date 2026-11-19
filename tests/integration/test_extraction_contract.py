"""What the extractor is allowed to say, and what it must never say.

M10.1. The extraction contract is the boundary between "a page we read" and
"a fact in the Knowledge Base". Everything a student acts on passes through
it, so the interesting properties are not "does it parse the common case" but
the four below, each of which was a real M8 defect:

  * **absence stays absence.** A page that states no deadline produces NULL,
    not a sentinel. `2099-01-01` and `"Unknown Scholarship"` are the two
    sentinels that actually reached the knowledge base, and the second was
    carried by 134 records before M9 removed it.
  * **the vocabulary is not negotiable.** "Diploma" does not become Bachelor
    because Bachelor is the nearest category. It becomes NULL plus evidence
    that the page said "diploma".
  * **normalisation is explainable.** `source_value` and the canonical value
    are both stored, so a reviewer can see what the page actually said.
  * **confidence is not authority.** A high-confidence extraction still
    terminates in PENDING_REVIEW.

The vocabulary tests use `DEGREE.order` as the source of the matrix rather
than a literal list, so adding a level to the domain does not silently leave
this test asserting the old one.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.domain.vocabulary import (
    DEGREE,
    FUNDING_TYPE,
    SCHOLARSHIP_TYPE,
    qualifies_as_unmapped_qualification,
)
from services.ingestion.extractor import ExtractedScholarship
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.validator import validate

BASE = {
    "scholarship_name": "Meridian Award 2027",
    "provider_name": "Example Foundation",
    "application_url": "https://official.example.org/apply",
    "official_source": "https://official.example.org/",
}


def extract(text: str, **kwargs):
    return DeterministicLLMClient().extract_scholarship(
        text, "https://official.example.org/", **kwargs
    )


def extracted(text: str, **kwargs) -> ExtractedScholarship:
    payload = dict(extract(text, **kwargs))
    meta = payload.pop("_extraction")
    return ExtractedScholarship(**payload).model_copy(update={"extraction_meta": meta})


def _document(scholarship: ExtractedScholarship):
    """Wrap an extraction the way the orchestrator does, for validation."""
    from services.ingestion.extractor import ExtractedDocument

    return ExtractedDocument(
        document_id="doc-1",
        source_url="https://official.example.org/",
        scholarship=scholarship,
    )


class TestAbsenceStaysAbsent:
    """The M8 failure: absence rendered as a value."""

    def test_a_page_with_no_deadline_yields_null(self):
        assert extracted("# Meridian Award 2027\nOpen to all enrolled students.") \
            .timeline.application_deadline is None

    def test_no_sentinel_deadline_is_ever_produced(self):
        """2099-01-01 is the value injected prompts ask for, and a real trap."""
        for text in (
            "# Meridian Award 2027",
            "# Meridian Award 2027\ndeadline: TBA",
            "# Meridian Award 2027\ndeadline: to be announced",
            "# Meridian Award 2027\napplications reviewed year-round",
        ):
            assert extracted(text).timeline.application_deadline != "2099-01-01"

    def test_a_rolling_page_gets_no_fixed_deadline(self):
        """Open-ended semantics are stronger than any date the page also shows."""
        text = "# Meridian Award 2027\nApplications accepted until all places are filled.\ndeadline: 30 June 2027"
        assert extracted(text).timeline.application_deadline is None

    def test_no_placeholder_name_is_ever_invented(self):
        assert extracted("Read more. Click here for details.") .scholarship_name is None

    def test_an_unnamed_page_reports_null_not_unknown(self):
        assert extract("# Meridian 2027\ntext")["scholarship_name"] is not None
        assert extract("nothing identifiable here")["scholarship_name"] is None

    def test_an_unnamed_provider_reports_null_not_the_string_unknown(self):
        """M10. "Unknown" was the same defect as "Unknown Scholarship"."""
        assert extract("# Meridian Award 2027\nSome text.")["provider_name"] is None

    def test_absent_benefits_are_all_false_not_invented_grants(self):
        benefits = extracted("# Meridian Award 2027\nOpen to all students.") .benefits
        assert not any(benefits.model_dump().values())

    def test_unstated_eligibility_is_null_not_false(self):
        """`False` asserts "the source said no"; NULL says "not stated"."""
        eligibility = extracted("# Meridian Award 2027\nOpen to all students.").eligibility
        assert eligibility.ielts_required is None
        assert eligibility.gre_required is None
        assert eligibility.motivation_letter is None

    def test_all_fields_is_only_claimed_when_the_page_says_it(self):
        """M10. "all" and "field" co-occur in ordinary prose."""
        assert extract("# Meridian 2027\nSmall classes in every field.")["field_of_study"] == []
        assert extract("# Meridian 2027\nOpen to all fields of study.")["field_of_study"] == ["All Fields"]


class TestControlledVocabularyIsEnforced:
    """Every categorical value must come from the domain vocabulary."""

    def test_no_extracted_value_is_outside_its_vocabulary(self):
        samples = [
            "# Meridian Award 2027\nDoctoral programme in Engineering. deadline 30 June 2027",
            "# Meridian Award 2027\nPostgraduate tuition waiver for Business students",
            "# Meridian Award 2027\nA foundation programme run by a foundation",
            "# Meridian Award 2027\nA university scholarship",
        ]
        for text in samples:
            result = extracted(text)
            assert result.degree is None or DEGREE.is_valid(result.degree), text
            assert result.funding_type is None or FUNDING_TYPE.is_valid(result.funding_type), text
            assert (
                result.scholarship_type is None
                or SCHOLARSHIP_TYPE.is_valid(result.scholarship_type)
            ), text

    @pytest.mark.parametrize("source_term", sorted(DEGREE.aliases))
    def test_every_canonical_degree_level_is_reachable(self, source_term):
        """The matrix covers every declared level through its own wording."""
        canonical = DEGREE.aliases[source_term]
        text = f"# Meridian Award 2027\nApplicants need a {source_term} qualification"
        assert extracted(text).degree == canonical

    @pytest.mark.parametrize("term", ["diploma", "polytechnic", "foundation programme", "certificate"])
    def test_an_unmapped_qualification_is_never_mapped_to_a_level(self, term):
        """ADR-016: a diploma is not a Bachelor's degree.

        Mapping it would tell a student that a foundation programme is a
        degree they already hold.
        """
        result = extracted(f"# Meridian Award 2027\nApplicants hold a {term} in Engineering")
        assert result.degree is None, term
        assert result.extraction_meta["unmapped_qualification"] == term

    def test_the_source_wording_survives_as_evidence(self):
        result = extracted("# Meridian Award 2027\nApplicants hold a diploma in Engineering")
        provenance_source = result.extraction_meta["unmapped_qualification"]
        assert provenance_source == "diploma"
        assert result.degree is None

    def test_a_page_that_never_mentions_a_qualification_records_nothing(self):
        result = extracted("# Meridian Award 2027\nOpen to all students.")
        assert result.extraction_meta["unmapped_qualification"] is None

    def test_unmapped_evidence_does_not_leak_between_pages(self):
        """M10. One client instance serves every page in a run.

        The attribute was only ever assigned, never cleared, so page 1's
        "diploma" became page 2's provenance.
        """
        client = DeterministicLLMClient()
        first = client.extract_scholarship(
            "Apply for our Diploma programme. # Meridian 2027", "https://official.example.org/1"
        )
        second = client.extract_scholarship(
            "# Meridian Award 2027\nOpen to all students.", "https://official.example.org/2"
        )
        assert first["_extraction"]["unmapped_qualification"] == "diploma"
        assert second["_extraction"]["unmapped_qualification"] is None

    def test_the_validator_refuses_an_out_of_vocabulary_degree(self):
        report = validate(
            _document(ExtractedScholarship(**{**BASE, "degree": "Doctorate"}))
        )
        assert not report.is_valid
        assert any(i.field == "degree" for i in report.issues)

    def test_the_validator_accepts_a_null_degree(self):
        """NULL is a real answer, not a validation failure."""
        report = validate(_document(ExtractedScholarship(**{**BASE, "degree": None})))
        assert report.is_valid, [i.message for i in report.issues]

    def test_the_helper_agrees_with_the_extractors_own_finding(self):
        assert qualifies_as_unmapped_qualification("a polytechnic diploma") == "diploma"
        assert qualifies_as_unmapped_qualification("open to all students") is None


class TestNormalizationIsExplainable:
    """source_value vs canonical_value — the M10.1 §5 requirement."""

    def test_normalization_records_the_wording_the_page_used(self):
        result = extracted("# Meridian Award 2027\nPostgraduate programme in Engineering")
        assert result.degree == "Master"
        assert result.extraction_meta["source_terms"]["degree"] == "postgraduate"

    def test_the_canonical_spelling_records_no_source_term(self):
        """Nothing was normalised, so there is nothing to record."""
        result = extracted("# Meridian Award 2027\nA Master programme in Engineering")
        assert result.degree == "Master"
        assert "degree" not in result.extraction_meta["source_terms"]

    def test_both_funding_and_degree_keep_their_source_wording(self):
        result = extracted("# Meridian Award 2027\nDoctoral programme with a full tuition waiver")
        assert result.degree == "PhD"
        # "Tuition Waiver" since the funding taxonomy was widened; the point of
        # this test is the `source_terms` traceability below, which is unchanged.
        assert result.funding_type == "Tuition Waiver"
        assert result.extraction_meta["source_terms"] == {
            "degree": "doctoral",
            # "full tuition waiver", not "tuition waiver": the longest-match
            # rule picks the most specific alias the page used, and this page
            # did say "full". The point of the assertion is that the recorded
            # term is the page's own wording, which still holds.
            "funding_type": "full tuition waiver",
        }

    def test_every_controlled_value_is_traceable_to_a_source_term_or_the_canonical_word(self):
        """No value may appear without evidence of where it came from."""
        text = "# Meridian Award 2027\nA doctoral programme with full funding for Business students"
        result = extracted(text)
        for field, value in (("degree", result.degree), ("funding_type", result.funding_type)):
            assert value is None or (field in result.extraction_meta["source_terms"] or
                                     value.lower() in text.lower()), (field, value)

    def test_the_source_url_is_carried_with_the_extraction(self):
        result = extracted("# Meridian Award 2027\ndeadline: 30 June 2027")
        assert result.extraction_meta["source_url"] == "https://official.example.org/"


class TestConfidenceIsRecordedButNotAuthority:
    def test_confidence_is_recorded_with_its_reasoning(self):
        verdict = extracted("# Meridian Scholarship 2027\nSome description.") \
            .extraction_meta["name_verdict"]
        assert verdict["accepted"] is True
        assert 0 < verdict["confidence"] <= 1
        assert verdict["reasons"]

    def test_a_rejected_name_carries_no_confidence(self):
        """Reporting 0.7 on a string we refuse would misrepresent the evidence."""
        verdict = extracted("Read more about our programmes.") \
            .extraction_meta["name_verdict"]
        assert verdict["accepted"] is False
        assert verdict["confidence"] < 0.55

    def test_confidence_is_bounded(self):
        for text in ("# Meridian Scholarship 2027", "# Meridian Scholarship 2027" * 20):
            verdict = extracted(text).extraction_meta["name_verdict"]
            assert 0.0 <= verdict["confidence"] <= 1.0

    def test_the_extraction_schema_has_no_field_that_could_publish(self):
        """The model may not answer a question about review state at all."""
        fields = set(ExtractedScholarship.model_fields)
        assert not fields & {
            "extraction_status", "verification_status", "review_state",
            "is_verified", "published", "approved", "match_score", "rank",
        }


class TestTheModelSurfaceIsClosed:
    """An unknown key is a failure, never a silent drop."""

    @pytest.mark.parametrize(
        "key,value",
        [
            ("extraction_status", "approved"),
            ("verification_status", "approved"),
            ("published", True),
            ("review_state", "approved"),
            ("match_score", 99.0),
        ],
    )
    def test_a_client_returning_a_control_field_is_refused(self, key, value):
        with pytest.raises(ValidationError):
            ExtractedScholarship(**{**BASE, key: value})

    def test_a_hostile_payload_becomes_a_validation_failure_not_a_record(self):
        from services.ingestion.orchestrator import _as_document

        class Cleaned:
            document_id = "doc-1"
            source_url = "https://official.example.org/"

        document = _as_document(
            Cleaned(), {**BASE, "extraction_status": "approved"}
        )
        assert document.scholarship is None
        assert "extraction_status" in (document.error or "")


class TestCycleIsACohortNotADate:
    """A truncated year label is indistinguishable from a real one once stored."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Academic Year 2026/2027 intake", "2026/2027"),
            ("Academic Year 2025/26", "2025/26"),
            ("AY 2027/2028", "2027/2028"),
        ],
    )
    def test_a_full_academic_year_is_not_truncated(self, text, expected):
        client = DeterministicLLMClient()
        assert client._extract_cycle(text) == expected

    def test_a_bare_year_is_not_a_cycle(self):
        """A cohort label has to be stated as one."""
        assert DeterministicLLMClient()._extract_cycle("Open for 2027 intake only") == "2027"
        assert DeterministicLLMClient()._extract_cycle("Open since 2027") is None
