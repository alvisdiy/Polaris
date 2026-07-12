"""Result models for the Scholarship Intelligence Engine."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class GapReport(BaseModel):
    """Describes a gap between user profile and scholarship requirement."""

    model_config = ConfigDict(frozen=True)

    field: str
    requirement: str
    user_value: str
    gap_description: str


class MatchResult(BaseModel):
    """Complete match result for a single scholarship."""

    model_config = ConfigDict(frozen=True)

    scholarship_id: str
    scholarship_name: str
    match_score: float
    recommendation_category: str
    criteria_scores: CriteriaScores
    strengths: list[str] = Field(default_factory=list)
    gaps: list[GapReport] = Field(default_factory=list)
    official_url: str


class Explanation(BaseModel):
    """Human-readable explanation for a match result."""

    model_config = ConfigDict(frozen=True)

    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
