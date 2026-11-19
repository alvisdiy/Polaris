"""Shared domain semantics: things more than one layer must agree on.

Vocabulary lives here because it has no single owner. The API describes the
accepted values, ingestion checks them, matching normalises to them, the review
service refuses everything else, and the database constrains them. Any of those
layers holding the definition would only relocate the duplication that Phase 4
removed.
"""

from .vocabulary import (
    CONTROLLED_VOCABULARIES,
    DEGREE,
    DEGREE_ALIASES,
    DEGREE_LEVELS,
    DEGREE_VALUES,
    EXPERIENCE,
    EXPERIENCE_ALIASES,
    EXPERIENCE_LEVELS,
    EXPERIENCE_VALUES,
    FUNDING_ALIASES,
    FUNDING_TYPE,
    FUNDING_TYPES,
    FUNDING_VALUES,
    SCHOLARSHIP_TYPE,
    SCHOLARSHIP_TYPE_ALIASES,
    SCHOLARSHIP_TYPE_VALUES,
    SCHOLARSHIP_TYPES,
    UNMAPPED_QUALIFICATION_NOTE,
    UNMAPPED_QUALIFICATION_TERMS,
    InvalidVocabularyValue,
    Vocabulary,
    get,
    is_valid,
    normalize,
    qualifies_as_unmapped_qualification,
    validate,
)

__all__ = [
    "CONTROLLED_VOCABULARIES",
    "DEGREE",
    "DEGREE_ALIASES",
    "DEGREE_LEVELS",
    "DEGREE_VALUES",
    "EXPERIENCE",
    "EXPERIENCE_ALIASES",
    "EXPERIENCE_LEVELS",
    "EXPERIENCE_VALUES",
    "FUNDING_ALIASES",
    "FUNDING_TYPE",
    "FUNDING_TYPES",
    "FUNDING_VALUES",
    "SCHOLARSHIP_TYPE",
    "SCHOLARSHIP_TYPES",
    "SCHOLARSHIP_TYPE_ALIASES",
    "SCHOLARSHIP_TYPE_VALUES",
    "UNMAPPED_QUALIFICATION_NOTE",
    "UNMAPPED_QUALIFICATION_TERMS",
    "InvalidVocabularyValue",
    "Vocabulary",
    "get",
    "is_valid",
    "normalize",
    "qualifies_as_unmapped_qualification",
    "validate",
]
