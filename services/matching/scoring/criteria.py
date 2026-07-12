"""Scoring criteria weights — configurable, defaults from matching-engine-spec."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CriteriaWeights:
    """Weights for each matching criterion. Total must equal 100."""

    country: float = 20.0
    degree: float = 20.0
    field_of_study: float = 20.0
    gpa: float = 15.0
    language: float = 10.0
    funding: float = 5.0
    research: float = 5.0
    work: float = 3.0
    leadership: float = 2.0

    def total(self) -> float:
        return (
            self.country
            + self.degree
            + self.field_of_study
            + self.gpa
            + self.language
            + self.funding
            + self.research
            + self.work
            + self.leadership
        )


# Default weights from matching-engine-design-specification.md
DEFAULT_WEIGHTS = CriteriaWeights()
