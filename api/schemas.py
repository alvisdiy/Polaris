"""Request and response schemas for the Recommendation API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    """Student profile for scholarship matching.

    All fields represent the student's current academic status and preferences.
    The matching engine uses these to score and rank available scholarships.
    """

    target_country: str = Field(
        ...,
        description="Target country for study (e.g., 'Japan', 'Germany', 'South Korea').",
        examples=["Japan"],
    )
    degree: str = Field(
        ...,
        description="Target degree level. Valid: Bachelor, Master, PhD, Exchange, Short Course.",
        examples=["Master"],
    )
    field_of_study: list[str] = Field(
        ...,
        min_length=1,
        description="List of fields of study. At least one required.",
        examples=[["Computer Science", "Artificial Intelligence"]],
    )
    current_gpa: float = Field(
        ...,
        ge=0.0,
        le=4.0,
        description="Current GPA on a 4.0 scale.",
        examples=[3.5],
    )
    ielts_score: float | None = Field(
        default=None,
        ge=0.0,
        le=9.0,
        description="IELTS score (0.0–9.0). Null if not taken.",
        examples=[7.0],
    )
    toefl_score: int | None = Field(
        default=None,
        ge=0,
        le=120,
        description="TOEFL iBT score (0–120). Null if not taken.",
        examples=[100],
    )
    research_experience: str = Field(
        ...,
        description="Research experience level. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Preferred"],
    )
    work_experience: str = Field(
        ...,
        description="Work experience level. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Optional"],
    )
    publication: str = Field(
        ...,
        description="Publication experience. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Not Required"],
    )
    leadership: bool = Field(
        ...,
        description="Whether the student has leadership experience.",
        examples=[True],
    )
    funding_preference: str = Field(
        ...,
        description="Funding preference. Valid: Fully Funded, Partial Funded, Tuition Only.",
        examples=["Fully Funded"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "target_country": "Japan",
                    "degree": "Master",
                    "field_of_study": ["Computer Science", "Artificial Intelligence"],
                    "current_gpa": 3.5,
                    "ielts_score": 7.0,
                    "toefl_score": None,
                    "research_experience": "Preferred",
                    "work_experience": "Optional",
                    "publication": "Not Required",
                    "leadership": True,
                    "funding_preference": "Fully Funded",
                }
            ]
        }
    }


class RecommendationResponse(BaseModel):
    """Single scholarship recommendation with match details."""

    scholarship_name: str = Field(
        ...,
        description="Official scholarship name.",
        examples=["MEXT Scholarship 2027"],
    )
    provider_name: str = Field(
        ...,
        description="Name of the scholarship provider organization.",
        examples=["Ministry of Education, Culture, Sports, Science and Technology"],
    )
    country: str = Field(
        ...,
        description="Country where the scholarship is offered.",
        examples=["Japan"],
    )
    match_score: float = Field(
        ...,
        description="Match score from 0 to 100.",
        examples=[92.5],
    )
    recommendation_category: str = Field(
        ...,
        description="Recommendation category based on score.",
        examples=["Excellent Match"],
    )
    explanation: str = Field(
        ...,
        description="Human-readable summary of the match quality.",
        examples=["Excellent match (92.5/100). You meet most requirements for this scholarship."],
    )
    strengths: list[str] = Field(
        ...,
        description="List of matching strengths.",
        examples=[["Country matches target", "Degree matches target", "GPA meets minimum requirement"]],
    )
    gaps: list[str] = Field(
        ...,
        description="List of identified gaps between profile and requirements.",
        examples=[["Limited field of study overlap"]],
    )
    next_steps: list[str] = Field(
        ...,
        description="Recommended next actions for the student.",
        examples=[["Visit the official application page: https://www.studyinjapan.go.jp/en/"]],
    )
    official_url: str = Field(
        ...,
        description="URL to the official scholarship page.",
        examples=["https://www.studyinjapan.go.jp/en/"],
    )


class RecommendationListResponse(BaseModel):
    """Response containing ranked scholarship recommendations."""

    results: list[RecommendationResponse] = Field(
        ...,
        description="List of scholarship recommendations, sorted by match score descending.",
    )
    total: int = Field(
        ...,
        description="Total number of recommendations returned.",
        examples=[5],
    )


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str | list[str] = Field(
        ...,
        description="Error message or list of validation errors.",
        examples=["Internal server error"],
    )
