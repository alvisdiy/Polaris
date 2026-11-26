"""Validate extracted scholarship data against schema and business rules."""

from pydantic import BaseModel, ConfigDict, Field

from services.domain.vocabulary import DEGREE, FUNDING_PERIOD, FUNDING_TYPE, SCHOLARSHIP_TYPE
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
    # A missing name is a hard failure. M8 accepted "Unknown Scholarship" as
    # a name; M9 refuses to persist a record whose identity the extractor
    # could not establish.
    if s.scholarship_name is None or not s.scholarship_name.strip():
        meta = s.extraction_meta or {}
        reasons = (meta.get("name_verdict") or {}).get("reasons") or []
        detail = f" ({'; '.join(reasons[:3])})" if reasons else ""
        issues.append(
            ValidationIssue(
                field="scholarship_name",
                message=(
                    "Scholarship name could not be identified from the page"
                    + detail
                    + " — a human must identify this record from its source page"
                ),
            )
        )
    # M10: an unresolved provider is not an extraction error. The page simply
    # did not name its provider, and the mapper resolves one from the
    # SourceRegistry row that produced this document — which is better
    # provenance than a regex reading a sentence off a portal page. The
    # publication gate is what refuses to publish a record whose provider
    # could not be resolved at all.
    if s.provider_name is not None and not s.provider_name.strip():
        issues.append(ValidationIssue(field="provider_name", message="Provider name cannot be empty"))

    # 2. Enum Validations (optional)
    if s.scholarship_type is not None and not SCHOLARSHIP_TYPE.is_valid(s.scholarship_type):
        issues.append(
            ValidationIssue(
                field="scholarship_type",
                message=(
                    f"Invalid scholarship type '{s.scholarship_type}'. Must be one of {SCHOLARSHIP_TYPE.describe()}"
                ),
            )
        )

    # Controlled vocabularies come from services/domain/vocabulary.py. This list
    # used to be a private literal identical to three others, which is how the
    # extractor's "Doctorate" ended up valid here and invalid everywhere else.
    if s.degree is not None and not DEGREE.is_valid(s.degree):
        issues.append(
            ValidationIssue(
                field="degree",
                message=(
                    f"Invalid degree '{s.degree}'. Must be one of "
                    f"{DEGREE.describe()}, or empty when the source does not state one"
                ),
            )
        )

    if s.funding_type is not None and not FUNDING_TYPE.is_valid(s.funding_type):
        issues.append(
            ValidationIssue(
                field="funding_type",
                message=(f"Invalid funding type '{s.funding_type}'. Must be one of {FUNDING_TYPE.describe()}"),
            )
        )

    # Funding amount as stated (semantics A). The period is controlled for
    # the same reason funding_type is: a free-text period cannot be rendered
    # or compared. An amount without both a currency and a period is not a
    # stated figure, it is half of one, so it is refused rather than stored.
    if s.funding_period is not None and not FUNDING_PERIOD.is_valid(s.funding_period):
        issues.append(
            ValidationIssue(
                field="funding_period",
                message=(f"Invalid funding period '{s.funding_period}'. Must be one of {FUNDING_PERIOD.describe()}"),
            )
        )
    if s.funding_amount is not None:
        if s.funding_amount < 0:
            issues.append(
                ValidationIssue(field="funding_amount", message="Funding amount must not be negative")
            )
        if not s.funding_currency or not s.funding_period:
            issues.append(
                ValidationIssue(
                    field="funding_amount",
                    message="A funding amount requires the currency and period the source stated it in",
                )
            )
    if s.funding_currency is not None and (
        len(s.funding_currency) != 3
        or not s.funding_currency.isalpha()
        or s.funding_currency.upper() != s.funding_currency
    ):
        issues.append(
            ValidationIssue(
                field="funding_currency",
                message=f"Invalid funding currency '{s.funding_currency}'. Must be an uppercase ISO 4217 code",
            )
        )
    if s.funding_duration_months is not None and s.funding_duration_months <= 0:
        issues.append(
            ValidationIssue(
                field="funding_duration_months", message="Funding duration must be a positive number of months"
            )
        )

    # 3. URL Validations
    if s.application_url and not validate_url(s.application_url):
        issues.append(
            ValidationIssue(field="application_url", message=f"Invalid application URL: '{s.application_url}'")
        )
    elif not s.application_url:
        issues.append(
            ValidationIssue(
                field="application_url",
                message="Application URL was not identified from a labelled link",
                severity="warning",
            )
        )
    if s.official_source and not validate_url(s.official_source):
        issues.append(
            ValidationIssue(field="official_source", message=f"Invalid official source URL: '{s.official_source}'")
        )
    elif not s.official_source:
        issues.append(
            ValidationIssue(
                field="official_source",
                message="Official source URL was not identified from a labelled link",
                severity="warning",
            )
        )

    # 4. Timeline Date Validations (optional)
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
    # Note: application_deadline is optional – no required error if missing.

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
