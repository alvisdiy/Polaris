"""Result models for the Scholarship Intelligence Engine."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class CriterionResult:
    """Result of scoring a single criterion.

    Attributes:
        criterion: Name of the criterion (e.g. "country", "gpa").
        score: Partial score awarded (0 to weight).
        weight: Maximum possible score for this criterion.
        matched: Whether the criterion is fully satisfied.
        reason: Human-readable explanation of the score.
    """

    criterion: str
    score: float
    weight: float
    matched: bool
    reason: str


class CriteriaScores(BaseModel):
    """Individual criterion scores and total (0–100)."""

    model_config = ConfigDict(frozen=True)

    country: float = 0.0
    degree: float = 0.0
    field_of_study: float = 0.0
    gpa: float = 0.0
    language: float = 0.0
    funding: float = 0.0
    research: float = 0.0
    work: float = 0.0
    leadership: float = 0.0
    total: float = 0.0
    details: list[CriterionResult] = Field(default_factory=list)


class GapReport(BaseModel):
    """Describes a gap between user profile and scholarship requirement."""

    model_config = ConfigDict(frozen=True)

    field: str
    requirement: str
    user_value: str
    gap_description: str


class MatchExplanation(BaseModel):
    """Value object describing why a scholarship matches a profile."""

    model_config = ConfigDict(frozen=True)

    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    """Complete match result for a single scholarship."""

    model_config = ConfigDict(frozen=True)

    scholarship_id: str
    scholarship_name: str
    match_score: float
    recommendation_category: str
    criteria_scores: CriteriaScores
    explanation: MatchExplanation
    official_url: str
