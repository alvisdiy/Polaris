"""User Profile schema for the Scholarship Intelligence Engine."""

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    """Student profile used for scholarship matching.

    All fields are user-provided inputs. Validation and normalization
    are handled by ProfileValidator and ProfileNormalizer respectively.
    """

    model_config = ConfigDict(frozen=True)

    target_country: str
    degree: str
    field_of_study: list[str] = Field(min_length=1)
    current_gpa: float = Field(ge=0.0, le=4.0)
    ielts_score: float | None = Field(default=None, ge=0.0, le=9.0)
    toefl_score: int | None = Field(default=None, ge=0, le=120)
    research_experience: str
    work_experience: str
    publication: str
    leadership: bool
    funding_preference: str
