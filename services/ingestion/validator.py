"""Validate extracted scholarship data against schema and business rules."""

from pydantic import BaseModel, ConfigDict, Field

from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


def validate_url(url: str) -> bool:
    """Check if the string is a valid HTTP/HTTPS URL."""
    try:
        from urllib.parse import urlparse

        res = urlparse(url)
        return all([res.scheme in ("http", "https"), res.netloc])
    except Exception:
        return False


def validate_date(date_str: str) -> bool:
    """Validate ISO YYYY-MM-DD date format."""
    from datetime import datetime

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def validate(doc: ExtractedDocument) -> ValidationReport:
    """Validate ExtractedDocument against core business rules."""
    issues: list[ValidationIssue] = []

    if doc.error:
        issues.append(ValidationIssue(field="document", message=f"Extraction error: {doc.error}"))
        return ValidationReport(is_valid=False, issues=issues)

    if not doc.scholarship:
        issues.append(ValidationIssue(field="scholarship", message="Missing scholarship extraction data"))
        return ValidationReport(is_valid=False, issues=issues)

    s: ExtractedScholarship = doc.scholarship

    # 1. Required Field Validations
    if not s.scholarship_name.strip():
        issues.append(ValidationIssue(field="scholarship_name", message="Scholarship name cannot be empty"))
    if not s.provider_name.strip():
        issues.append(ValidationIssue(field="provider_name", message="Provider name cannot be empty"))

    # 2. Enum Validations
    valid_types = {"Government", "University", "Foundation", "NGO", "Company"}
    if s.scholarship_type not in valid_types:
        issues.append(
            ValidationIssue(
                field="scholarship_type",
                message=f"Invalid scholarship type '{s.scholarship_type}'. Must be one of {sorted(valid_types)}",
            )
        )

    valid_degrees = {"Bachelor", "Master", "PhD", "Exchange", "Short Course"}
    if s.degree not in valid_degrees:
        issues.append(
            ValidationIssue(
                field="degree", message=f"Invalid degree '{s.degree}'. Must be one of {sorted(valid_degrees)}"
            )
        )

    valid_fundings = {"Fully Funded", "Partial Funded", "Tuition Only"}
    if s.funding_type not in valid_fundings:
        issues.append(
            ValidationIssue(
                field="funding_type",
                message=f"Invalid funding type '{s.funding_type}'. Must be one of {sorted(valid_fundings)}",
            )
        )

    # 3. URL Validations
    if not validate_url(s.application_url):
        issues.append(
            ValidationIssue(field="application_url", message=f"Invalid application URL: '{s.application_url}'")
        )
    if not validate_url(s.official_source):
        issues.append(
            ValidationIssue(field="official_source", message=f"Invalid official source URL: '{s.official_source}'")
        )

    # 4. Timeline Date Validations
    t = s.timeline
    if t.application_open and not validate_date(t.application_open):
        issues.append(
            ValidationIssue(
                field="timeline.application_open",
                message=f"Invalid open date format: '{t.application_open}'",
            )
        )
    if t.application_deadline:
        if not validate_date(t.application_deadline):
            issues.append(
                ValidationIssue(
                    field="timeline.application_deadline",
                    message=f"Invalid deadline date format: '{t.application_deadline}'",
                )
            )
    else:
        issues.append(
            ValidationIssue(
                field="timeline.application_deadline",
                message="Application deadline is required",
            )
        )

    # Cross-field date check
    if (
        t.application_open
        and t.application_deadline
        and validate_date(t.application_open)
        and validate_date(t.application_deadline)
    ):
        if t.application_open > t.application_deadline:
            issues.append(
                ValidationIssue(
                    field="timeline",
                    message=(
                        f"Application open date '{t.application_open}' is after deadline '{t.application_deadline}'"
                    ),
                )
            )

    # 5. Eligibility Level Validations
    valid_req_levels = {"Required", "Preferred", "Optional", "Not Required"}
    el = s.eligibility
    if el.work_experience and el.work_experience not in valid_req_levels:
        issues.append(
            ValidationIssue(
                field="eligibility.work_experience",
                message=f"Invalid work experience level '{el.work_experience}'",
            )
        )
    if el.research_experience and el.research_experience not in valid_req_levels:
        issues.append(
            ValidationIssue(
                field="eligibility.research_experience",
                message=f"Invalid research experience level '{el.research_experience}'",
            )
        )
    if el.publication and el.publication not in valid_req_levels:
        issues.append(
            ValidationIssue(
                field="eligibility.publication",
                message=f"Invalid publication level '{el.publication}'",
            )
        )

    # GPA Bounds Check
    if el.minimum_gpa is not None and not (0.0 <= el.minimum_gpa <= 4.0):
        issues.append(
            ValidationIssue(
                field="eligibility.minimum_gpa",
                message=f"GPA '{el.minimum_gpa}' out of range (0.0 - 4.0)",
            )
        )

    # IELTS Bounds Check
    if el.minimum_ielts is not None and not (0.0 <= el.minimum_ielts <= 9.0):
        issues.append(
            ValidationIssue(
                field="eligibility.minimum_ielts",
                message=f"IELTS '{el.minimum_ielts}' out of range (0.0 - 9.0)",
            )
        )

    # Status check
    has_errors = any(issue.severity == "error" for issue in issues)

    return ValidationReport(is_valid=not has_errors, issues=issues)
