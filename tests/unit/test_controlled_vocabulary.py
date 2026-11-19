"""Unit tests for the canonical controlled vocabulary (M9.1 Phase 4).

Finding #3 was that a reviewer could publish ``degree="Polytechnic"`` because
no boundary validated it, and that the degree list was independently written in
four places — one of which (the extractor) had already drifted by adding
"Doctorate", a value its own validator rejected.

These tests pin the two properties that fix that: the canonical definition is
the only one, and normalisation never invents a category the domain does not
declare.
"""

from __future__ import annotations

import pytest

from services.domain import vocabulary as V
from services.domain.vocabulary import (
    DEGREE,
    FUNDING_TYPE,
    InvalidVocabularyValue,
    is_valid,
    normalize,
    qualifies_as_unmapped_qualification,
    validate,
)
from services.ingestion.real_extractor import DeterministicLLMClient
from services.matching.models.profile import UserProfile
from services.matching.profile.normalizer import ProfileNormalizer
from services.matching.profile.validator import (
    VALID_DEGREES,
    VALID_FUNDING_PREFERENCES,
    ProfileValidator,
)


class TestCanonicalDefinition:
    def test_degree_values_are_the_documented_five(self):
        """data-dictionary.md §Degree is the contract; ADR-016 did not widen it."""
        assert V.DEGREE_LEVELS == (
            "Bachelor",
            "Exchange",
            "Master",
            "PhD",
            "Short Course",
        )
        assert V.DEGREE_VALUES == set(V.DEGREE_LEVELS)

    def test_one_definition_shared_by_every_consumer(self):
        """The four former duplicates must be the same object, not equal copies.

        Identity rather than equality: a copy is exactly how the lists drifted
        apart in the first place.
        """
        from services.ingestion import validator as ingestion_validator
        from services.matching.profile import validator as profile_validator

        assert profile_validator.VALID_DEGREES is V.DEGREE_VALUES
        assert profile_validator.VALID_FUNDING_PREFERENCES is V.FUNDING_VALUES
        # The ingestion validator no longer defines its own literals at all.
        source = V.__file__
        assert source
        with open(ingestion_validator.__file__, encoding="utf-8") as handle:
            text = handle.read()
        assert '"Bachelor", "Master", "PhD"' not in text
        assert "VALID_DEGREES" not in text

    def test_extractor_cannot_emit_a_value_the_validator_rejects(self):
        """The old 'Doctorate' bug: extractor and validator disagreed."""
        extractor = DeterministicLLMClient()
        for text, expected in [
            ("Applicants must hold a Doctorate degree", "PhD"),
            ("Applicants must hold a Ph.D. in engineering", "PhD"),
            ("Applicants must hold a Master's degree", "Master"),
            ("Applicants must hold a bachelor's degree", "Bachelor"),
        ]:
            result = extractor._extract_degree(text)
            assert result == expected, f"{text!r} produced {result!r}"
            assert is_valid("degree", result), f"{result!r} would be rejected downstream"

    def test_every_alias_maps_to_a_declared_value(self):
        """An alias pointing outside the vocabulary would be a silent hole."""
        for vocabulary in (DEGREE, FUNDING_TYPE, V.EXPERIENCE, V.SCHOLARSHIP_TYPE):
            for canonical in vocabulary.aliases.values():
                assert canonical in vocabulary.values, (
                    f"{vocabulary.name} alias maps to undeclared {canonical!r}"
                )

    def test_every_canonical_value_round_trips(self):
        for vocabulary in (DEGREE, FUNDING_TYPE, V.EXPERIENCE):
            for value in vocabulary.values:
                assert vocabulary.normalize(value) == value
                assert vocabulary.normalize(value.lower()) == value or value in vocabulary.aliases.values()


class TestValidation:
    @pytest.mark.parametrize("value", ["Bachelor", "Exchange", "Master", "PhD", "Short Course"])
    def test_valid_degree_accepted(self, value):
        validate("degree", value)

    @pytest.mark.parametrize(
        "value", ["Polytechnic", "Diploma", "Postgraduate", "bachelors", "", "  "]
    )
    def test_invalid_degree_rejected(self, value):
        with pytest.raises(InvalidVocabularyValue):
            validate("degree", value)

    def test_none_is_accepted_because_the_source_may_be_silent(self):
        validate("degree", None)
        validate("funding_type", None)

    def test_free_text_fields_are_not_constrained(self):
        """field_of_study is an open taxonomy; a new major must not be refused."""
        for value in ("Nursing", "Marine Biology", "Civil Engineering"):
            validate("field_of_study", value)
            assert is_valid("field_of_study", value)

    def test_error_names_field_value_allowed_and_nullability(self):
        """A reviewer must be able to fix this without reading the source."""
        with pytest.raises(InvalidVocabularyValue) as exc:
            validate("degree", "Polytechnic")
        message = str(exc.value)
        assert "degree" in message
        assert "Polytechnic" in message
        for value in V.DEGREE_LEVELS:
            assert value in message
        assert "left empty" in message

    def test_error_suggests_a_canonical_spelling_without_coercing(self):
        with pytest.raises(InvalidVocabularyValue) as exc:
            validate("degree", "masters")
        assert "Master" in str(exc.value)
        # A suggestion is advice; the value is still refused.
        with pytest.raises(InvalidVocabularyValue):
            validate("degree", "masters")

    def test_funding_type_validated(self):
        validate("funding_type", "Fully Funded")
        with pytest.raises(InvalidVocabularyValue):
            validate("funding_type", "Completely Free")


class TestNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("master's", "Master"),
            ("masters", "Master"),
            ("m.sc.", "Master"),
            ("bachelor", "Bachelor"),
            ("bsc", "Bachelor"),
            ("ph.d.", "PhD"),
            ("doctorate", "PhD"),
            ("short course", "Short Course"),
            ("Master", "Master"),
        ],
    )
    def test_known_synonyms_become_canonical(self, raw, expected):
        assert normalize("degree", raw) == expected

    @pytest.mark.parametrize(
        "term", ["diploma", "polytechnic", "foundation programme", "certificate", "pgdip"]
    )
    def test_qualification_terms_are_never_mapped(self, term):
        """ADR-016: a diploma is not a Bachelor's degree."""
        assert normalize("degree", term) is None

    def test_diploma_is_never_mapped_to_bachelor(self):
        assert normalize("degree", "diploma") != "Bachelor"
        assert normalize("degree", "polytechnic diploma") != "Bachelor"
        assert normalize("degree", "Higher Diploma") != "Bachelor"

    def test_profile_normalizer_does_not_invent_a_degree(self):
        normalizer = ProfileNormalizer()
        profile = UserProfile(
            target_country="Singapore",
            degree="Diploma",
            field_of_study=["Computer Science"],
            current_gpa=3.5,
            ielts_score=7.0,
            toefl_score=None,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        # Normalisation leaves it alone...
        assert normalizer.normalize(profile).degree == "Diploma"
        # ...so validation reports it rather than silently accepting it.
        errors = ProfileValidator().validate(normalizer.normalize(profile))
        assert any("Invalid degree" in e for e in errors)

    def test_profile_normalizer_maps_known_synonyms(self):
        normalizer = ProfileNormalizer()
        profile = UserProfile(
            target_country="Singapore",
            degree="master's",
            field_of_study=["Computer Science"],
            current_gpa=3.5,
            ielts_score=7.0,
            toefl_score=None,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="full",
        )
        normalized = normalizer.normalize(profile)
        assert normalized.degree == "Master"
        assert normalized.funding_preference == "Fully Funded"
        assert ProfileValidator().validate(normalized) == []

    def test_normalization_is_idempotent(self):
        normalizer = ProfileNormalizer()
        profile = UserProfile(
            target_country="Singapore",
            degree="ph.d.",
            field_of_study=["cs"],
            current_gpa=3.5,
            ielts_score=7.0,
            toefl_score=None,
            research_experience="mandatory",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        once = normalizer.normalize(profile)
        assert normalizer.normalize(once) == once

    def test_extractor_returns_none_for_an_unmapped_qualification(self):
        extractor = DeterministicLLMClient()
        text = (
            "The Polytechnic Foundation Programme awards a diploma to eligible "
            "candidates. Applicants must have completed secondary school."
        )
        assert extractor._extract_degree(text) is None

    def test_extractor_records_the_source_terminology_as_evidence(self):
        """The wording is kept so a reviewer sees why degree is empty."""
        extractor = DeterministicLLMClient()
        text = "Eligible applicants must hold a Higher Diploma qualification."
        assert extractor._extract_degree(text) is None
        assert extractor.last_unmapped_qualification is not None
        assert "diploma" in extractor.last_unmapped_qualification

    def test_unmapped_qualification_detector(self):
        assert qualifies_as_unmapped_qualification("a diploma programme") == "diploma"
        assert qualifies_as_unmapped_qualification("polytechnic foundation") == "polytechnic"
        assert qualifies_as_unmapped_qualification("a Master's degree") is None
        assert qualifies_as_unmapped_qualification(None) is None

    def test_extracted_funding_type_is_always_canonical(self):
        extractor = DeterministicLLMClient()
        for text in [
            "This is a fully funded scholarship.",
            "Applicants receive a tuition only award.",
            "Partial funded support is available.",
        ]:
            value = extractor._extract_funding_type(text)
            assert value is None or is_valid("funding_type", value)


class TestPublicApiCompatibility:
    def test_documented_degree_list_is_unchanged(self):
        """No public value changes; only the definition's location moved."""
        from api.schemas import RecommendationRequest

        description = RecommendationRequest.model_fields["degree"].description
        for value in V.DEGREE_LEVELS:
            assert value in description

    def test_existing_profiles_still_validate(self):
        """Every degree a shipped test used must still be accepted."""
        for degree in ("Bachelor", "Master", "PhD", "Exchange", "Short Course"):
            assert degree in VALID_DEGREES
        for funding in ("Fully Funded", "Partial Funded", "Tuition Only"):
            assert funding in VALID_FUNDING_PREFERENCES
