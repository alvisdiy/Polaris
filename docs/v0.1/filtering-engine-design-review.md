# Filtering Engine Design Review v1.0 (Approved)

## Polaris — Scholarship Intelligence Engine (SIE)

**Version:** 1.0 — Final
**Owner:** AlVis
**Status:** Approved
**Date:** 2026-07-12

---

# Revision History

| Version | Date | Status | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-07-12 | Draft | Initial design review |
| 0.2 | 2026-07-12 | Revised | Country/Field re-evaluated, Mandatory vs Preference, three-layer separation |
| 1.0 | 2026-07-12 | **Approved** | Definitive decisions on all criteria. No unresolved alternatives. |

---

# Purpose

This document is the final, approved design for the Filtering Engine. It resolves all architectural conflicts from prior drafts, assigns each criterion to exactly one execution layer, and produces the implementation-ready API.

---

# 1. Design Principles

1. **The Data Dictionary is the authoritative source for matching criteria and weights.** When the Matching Engine Spec and Data Dictionary conflict on classification, the Data Dictionary governs because it defines the schema contract.
2. **Each criterion belongs to exactly one layer.** No criterion is both a filter and a scoring criterion.
3. **The Repository retrieves data.** Business rules belong to the application/service layer. The only exception is `extraction_status`, which is a data-governance gate, not a business rule.
4. **The FilterEngine applies mandatory, non-negotiable filters only.** It does not express user preferences. User preferences are scoring criteria.
5. **Scoring produces a spectrum, not a binary.** A zero score does not eliminate — it ranks last.

---

# 2. Definitive Criterion Classification

## 2.1 Final Decisions

### Decision 1: Country is a Scoring Criterion, not a Filter.

**Rationale:** The Data Dictionary assigns Country a weight of 20. This means Country produces a 0–20 score spectrum, not a binary pass/fail. A hard filter contradicts a weight assignment — a hard-filtered criterion has weight ∞ (eliminated) or 0 (passed), not 20. The Matching Engine Spec's phrase "Negara tidak sesuai (jika user memilih negara tertentu)" describes a scenario where a low score effectively excludes, not a system-enforced filter.

**Effect:** A scholarship in Germany scores 0/20 on Country for a Japan-targeting user. Combined with other criteria, it ranks below matching scholarships. If the user sets `target_countries = []` (any country), all countries score 20/20.

### Decision 2: Degree is a Scoring Criterion, not a Filter.

**Rationale:** The Data Dictionary assigns Degree a weight of 20. The same logic as Country applies. A Bachelor scholarship scores 0/20 on Degree for a Master-targeting user. The Matching Engine Spec's "Degree tidak sesuai" describes a scoring outcome (0 points), not a separate filter stage. Treating Degree as both a filter (weight ∞) and a scoring criterion (weight 20) is contradictory. The Data Dictionary governs.

**Effect:** A Bachelor scholarship is not hidden from a Master's user — it scores 0/20 on Degree and ranks at the bottom. This is more transparent: the user can see that the scholarship exists but doesn't match their degree preference.

### Decision 3: Field of Study is a Scoring Criterion, not a Filter.

**Rationale:** The Data Dictionary assigns Field of Study a weight of 20. A hard filter on field overlap is inconsistent with a scoring weight. Zero overlap produces 0/20, which combined with other criteria results in a low total score. The ranking engine naturally excludes low-scoring results from the Top-N output.

**Effect:** A Mathematics scholarship scores 0/20 on Field for a CS user. It ranks below overlapping scholarships. It is not hidden.

### Decision 4: Deadline is a Mandatory Filter in the FilterEngine.

**Rationale:** An expired scholarship is objectively non-actionable. Unlike Country/Degree/Field, there is no scenario where a user wants to see expired scholarships. This is not a preference — it is a hard constraint on data quality. Unlike `extraction_status` (which gates data before it enters the system), deadline is a time-dependent constraint that must be evaluated at query time.

**Effect:** Scholarships with `application_deadline < today` are excluded. Scholarships with `application_deadline IS NULL` (open-ended) pass.

### Decision 5: Extraction Status is a Repository-level data-governance filter.

**Rationale:** `extraction_status` controls whether data has completed the human-review pipeline (ADR-012, ADR-015). This is a data-governance gate — it determines which records are considered "published." It is not a matching business rule. The Repository applies it as part of data retrieval, similar to a soft-delete pattern.

**Architectural exception documented:** The Repository pattern dictates that the Repository should only retrieve data without business logic. `extraction_status = 'approved'` is the one documented exception — it is a data-governance filter, not a matching preference. It belongs at the data-access layer because it controls which data enters the entire system, not just the matching engine.

---

## 2.2 Final Classification Table

| # | Criterion | DB Field | Layer | Type | Weight |
|---|-----------|----------|-------|------|--------|
| F1 | Extraction Status | `scholarship.extraction_status` | L0 Repository | **Data-Governance Filter** | N/A (pre-filter) |
| F2 | Deadline Validity | `timeline.application_deadline` | L1 FilterEngine | **Mandatory Filter** | N/A (binary) |
| S1 | Country Match | `country.name` | L2 ScoringEngine | **Scoring Criterion** | 20 |
| S2 | Degree Match | `scholarship.degree` | L2 ScoringEngine | **Scoring Criterion** | 20 |
| S3 | Field of Study | `scholarship.field_of_study` | L2 ScoringEngine | **Scoring Criterion** | 20 |
| S4 | GPA Fit | `requirement.minimum_gpa` | L2 ScoringEngine | **Scoring Criterion** | 15 |
| S5 | Language Fit | `requirement.minimum_ielts` / `minimum_toefl` | L2 ScoringEngine | **Scoring Criterion** | 10 |
| S6 | Funding Match | `scholarship.funding_type` | L2 ScoringEngine | **Scoring Criterion** | 5 |
| S7 | Research Experience | `requirement.research_experience` | L2 ScoringEngine | **Scoring Criterion** | 5 |
| S8 | Work Experience | `requirement.work_experience` | L2 ScoringEngine | **Scoring Criterion** | 3 |
| S9 | Leadership | `profile.leadership` | L2 ScoringEngine | **Scoring Criterion** | 2 |
| E1 | Benefits | `benefit.*` | L4 ExplanationEngine | **Explanation Only** | N/A |
| E2 | Timeline Details | `timeline.*` (beyond deadline) | L4 ExplanationEngine | **Explanation Only** | N/A |
| E3 | Provider Info | `provider.*` | L4 ExplanationEngine | **Explanation Only** | N/A |
| E4 | Data Completeness | Count of non-null fields | L3 RankingEngine | **Ranking Tiebreaker** | N/A |

**Total scoring weight: 100** (20+20+20+15+10+5+5+3+2)

## 2.3 Summary

| Category | Count | Criteria |
|----------|-------|----------|
| Data-Governance Filter (Repository) | 1 | Extraction Status |
| Mandatory Filter (FilterEngine) | 1 | Deadline Validity |
| Scoring Criterion (ScoringEngine) | 9 | Country, Degree, Field, GPA, Language, Funding, Research, Work, Leadership |
| Ranking Tiebreaker | 1 | Data Completeness |
| Explanation Only | 4 | Benefits, Timeline Details, Provider, Data Completeness |

---

# 3. Repository Responsibilities

## 3.1 Pattern Definition

The Repository Pattern separates data-access logic from business logic. The Repository is responsible for:
- Constructing and executing queries.
- Mapping database rows to domain objects.
- Managing eager/lazy loading.
- Handling transactions.

The Repository does NOT:
- Apply business rules (e.g., "user wants Japan" → filtering by country).
- Calculate scores.
- Rank results.

## 3.2 Documented Exception: extraction_status

`WHERE extraction_status = 'approved'` is the one documented exception to the pure Repository pattern.

**Why it's an exception:**
- It is not a matching business rule. It does not depend on the user profile.
- It is a system-wide data-governance gate. Unapproved data should not be visible to ANY consumer (API, matching engine, search, admin dashboard).
- It is analogous to a soft-delete pattern (`WHERE deleted_at IS NULL`), which is an accepted Repository responsibility.
- Moving it to the FilterEngine would require every consumer of the Repository to apply the same filter, violating DRY.

**Documented in:** This section (3.2) and the Architecture Decision Record.

## 3.3 What the Repository Does NOT Filter

The Repository does NOT apply:
- `WHERE degree = :target_degree` — this is a matching preference (ScoringEngine).
- `WHERE country_id = :target_country_id` — this is a matching preference (ScoringEngine).
- `WHERE field_of_study && :user_fields` — this is a matching preference (ScoringEngine).
- `WHERE application_deadline >= CURRENT_DATE` — this is a business rule (FilterEngine).

These filters belong to the application/service layer. The Repository retrieves all approved data; the service layer applies matching logic.

## 3.4 Repository Implementation

```python
class ScholarshipRepository:
    """Persistence layer for Scholarship aggregate.

    Applies extraction_status = 'approved' as a data-governance filter.
    All other filtering is the responsibility of the service layer.
    """

    def get_all_approved(self) -> list[Scholarship]:
        """Return all approved scholarships with eager-loaded children.

        Data-governance filter: only 'approved' records are returned.
        This is the one documented exception to the pure Repository pattern.
        """
        return (
            self.session.query(Scholarship)
            .options(
                joinedload(Scholarship.country),
                joinedload(Scholarship.requirement),
                joinedload(Scholarship.benefit),
                joinedload(Scholarship.timeline),
                joinedload(Scholarship.versions),
            )
            .filter(Scholarship.extraction_status == "approved")
            .all()
        )
```

---

# 4. FilterEngine — Final Design

## 4.1 Responsibility

The FilterEngine applies **mandatory, non-negotiable filters** that eliminate objectively non-actionable scholarships. It does NOT express user preferences. User preferences are scoring criteria handled by the ScoringEngine.

**Single predicate for MVP:** Deadline validity.

## 4.2 API

```python
class FilterEngine:
    """Applies mandatory filters to eliminate non-actionable scholarships.

    This is the L1 (Mandatory Filter) stage. It removes scholarships that
    no user would want, regardless of their preferences:
    - Expired deadlines (application_deadline < today)

    User preferences (country, degree, field, GPA, etc.) are handled by
    the ScoringEngine (L2), not here.

    The Repository (L0) handles extraction_status as a data-governance filter.
    """

    def filter(
        self,
        profile: UserProfile,
        scholarships: list[Scholarship],
    ) -> list[Scholarship]:
        """Return only non-expired scholarships.

        Args:
            profile: Normalized user profile (passed for API consistency
                and future extensibility; not used in MVP).
            scholarships: Approved scholarships from Repository (L0).

        Returns:
            List of non-expired scholarships.
        """
        return [s for s in scholarships if self._not_expired(s)]

    @staticmethod
    def _not_expired(scholarship: Scholarship) -> bool:
        """Deadline must be NULL (open-ended) or in the future."""
        if scholarship.timeline is None:
            return True
        deadline = scholarship.timeline.application_deadline
        if deadline is None:
            return True
        return deadline >= date.today()
```

## 4.3 Why profile is Accepted but Not Used

The `filter(profile, scholarships)` signature accepts `profile` for:
- **API consistency:** All engine stages accept a profile. This prevents signature changes when future mandatory filters are added (e.g., age limit).
- **Future extensibility:** Age limit (`_meets_age_limit`) requires the profile's `date_of_birth`. The signature is already in place.

In MVP, `profile` is not used by `_not_expired`.

## 4.4 What Changed from M3.2

| Predicate | M3.2 (current) | v1.0 (this review) | Rationale |
|-----------|----------------|---------------------|-----------|
| `_matches_degree` | In FilterEngine | **Removed** → ScoringEngine (weight 20) | Data Dictionary assigns weight 20. Scoring criterion, not filter. |
| `_matches_country` | In FilterEngine | **Removed** → ScoringEngine (weight 20) | Data Dictionary assigns weight 20. Scoring criterion, not filter. |
| `_not_expired` | In FilterEngine | **Retained** | Mandatory filter. Expired scholarships are objectively non-actionable. |
| `_field_overlap` | In FilterEngine (v0.1), removed in v0.2 | **Removed** → ScoringEngine (weight 20) | Data Dictionary assigns weight 20. Scoring criterion, not filter. |

**Net effect:** FilterEngine goes from 4 predicates (M3.2) to 1 predicate (v1.0).

---

# 5. ScoringEngine — Final Design

## 5.1 Responsibility

The ScoringEngine calculates a weighted match score (0–100) for each scholarship against the user profile. It handles ALL user preferences — country, degree, field, GPA, language, funding, research, work, leadership.

## 5.2 Criteria and Weights

| # | Criterion | Weight | Scoring Logic |
|---|-----------|-------:|---------------|
| S1 | Country | 20 | 20 if `country.name` in `profile.target_countries`, 0 otherwise. If `target_countries` is empty (any), always 20. |
| S2 | Degree | 20 | 20 if `scholarship.degree` in `profile.target_degrees`, 0 otherwise. If `target_degrees` is empty (any), always 20. |
| S3 | Field of Study | 20 | `20 * (overlap_count / scholarship_field_count)`. Empty scholarship fields = 20 (no restriction). |
| S4 | GPA | 15 | `15 * min(profile.gpa / min_gpa, 1.0)`. No minimum = 15. |
| S5 | Language | 10 | `10 * min(score / min_score, 1.0)`. Neither required = 10. |
| S6 | Funding | 5 | 5 if `funding_type == profile.funding_preference`, 0 otherwise. |
| S7 | Research | 5 | Ordinal: meets requirement = 5, one level below = 2.5, else 0. No requirement = 5. |
| S8 | Work | 3 | Ordinal: same as research. No requirement = 3. |
| S9 | Leadership | 2 | 2 if `profile.leadership` is True, 0 otherwise. |

**Total: 100**

## 5.3 Country Scoring — Detail

```python
def _score_country(self, profile: UserProfile, scholarship: Scholarship) -> float:
    """Country match — scoring criterion, not a filter.

    If profile has no country preference (empty list), all countries
    score 20/20 (no penalty).
    """
    if not profile.target_countries:  # "any country"
        return self._w.country
    if scholarship.country and scholarship.country.name in profile.target_countries:
        return self._w.country
    return 0.0
```

**MVP note:** The current `UserProfile.target_country: str` is a single required field. For MVP scoring, treat it as `target_countries = [target_country]`. When multi-country support is added, change the field to `target_countries: list[str]`.

## 5.4 Degree Scoring — Detail

```python
def _score_degree(self, profile: UserProfile, scholarship: Scholarship) -> float:
    """Degree match — scoring criterion, not a filter.

    If profile has no degree preference (empty list), all degrees
    score 20/20 (no penalty).
    """
    if not profile.target_degrees:  # "any degree"
        return self._w.degree
    if scholarship.degree in profile.target_degrees:
        return self._w.degree
    return 0.0
```

**MVP note:** The current `UserProfile.degree: str` is a single required field. For MVP scoring, treat it as `target_degrees = [degree]`.

## 5.5 Implementation Status

The ScoringEngine (M3.3) already implements `_score_country`, `_score_degree`, and `_score_field` as scoring methods. These methods were previously called after the FilterEngine had already hard-filtered on these criteria. Under the v1.0 design, they become the sole handlers — the FilterEngine no longer pre-filters.

**No ScoringEngine code changes are required.** The existing `_score_country`, `_score_degree`, and `_score_field` methods already produce the correct 0–20 spectrum. The only change is that scholarships with 0 scores on these criteria now reach the ScoringEngine instead of being filtered out earlier.

---

# 6. Three-Layer Architecture — Final

## 6.1 Layer Diagram

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         USER PROFILE                                │
│  target_country, degree, field_of_study, gpa, ielts, ...           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  L0: REPOSITORY                                                     │
│  ───────────────                                                    │
│  Responsibility: Retrieve published data from database.             │
│  Filter: extraction_status = 'approved'                             │
│           (data-governance filter — documented exception)           │
│  Does NOT filter by: country, degree, field, deadline               │
│  Eager loads: country, requirement, benefit, timeline, versions     │
│  Output: list[Scholarship]                                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  L1: FILTER ENGINE                                                  │
│  ───────────────────                                                │
│  Responsibility: Remove objectively non-actionable scholarships.    │
│  Filter: application_deadline >= today OR NULL                      │
│           (mandatory filter — expired = non-actionable)             │
│  Does NOT filter by: country, degree, field (those are scoring)     │
│  Output: list[Scholarship]                                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  L2: SCORING ENGINE                                                 │
│  ──────────────────                                                 │
│  Responsibility: Calculate weighted match score (0–100).            │
│  Criteria (9):                                                      │
│    Country (20) · Degree (20) · Field (20) · GPA (15) ·            │
│    Language (10) · Funding (5) · Research (5) · Work (3) ·          │
│    Leadership (2)                                                   │
│  Output: list[(Scholarship, CriteriaScores)]                        │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  L3: RANKING ENGINE                                                 │
│  ──────────────────                                                 │
│  Responsibility: Sort by score, apply tiebreakers, return Top-N.    │
│  Sort keys: (1) total score ↓ (2) deadline ↑ (3) funding type      │
│             (4) data completeness                                   │
│  Default N: 10                                                      │
│  Output: list[MatchResult]                                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  L4: EXPLANATION ENGINE                                             │
│  ───────────────────────                                            │
│  Responsibility: Generate human-readable explanation per result.    │
│  Output: list[MatchResult + Explanation]                            │
└─────────────────────────────────────────────────────────────────────┘
```

## 6.2 Separation Rules

| Rule | Enforcement |
|------|-------------|
| L0 retrieves, does not match. | Repository returns all approved data. No country/degree/field filtering. |
| L1 filters, does not score. | FilterEngine removes expired scholarships only. No scoring. |
| L2 scores, does not filter. | ScoringEngine produces 0–100. Zero-scored scholarships remain in the list. |
| L3 ranks, does not re-filter. | RankingEngine sorts and truncates. Does not remove zero-scored items before sorting. |
| L4 explains, does not modify. | ExplanationEngine reads scores, does not change them. |
| Each layer is independently testable. | L0 requires DB. L1–L4 operate on in-memory objects. |

## 6.3 Why This Separation

| Concern | All-in-SQL Approach | Three-Layer Approach (chosen) |
|---------|--------------------|-----------------------------|
| Testability | Requires DB for all tests | L1–L4 testable without DB |
| Portability | Tied to PostgreSQL array operators | Domain logic portable across data sources |
| Flexibility | Changing filter logic requires SQL changes | Changes in Python, independent of DB |
| Debuggability | SQL results hard to inspect mid-pipeline | Each layer produces inspectable intermediate results |
| Consistency | Some criteria SQL-friendly, others not | All matching criteria handled uniformly in Python |

---

# 7. Sequence Diagram — Full Pipeline

## 7.1 End-to-End Flow

```text
 User
   │
   ▼
 ┌─────────────────────┐
 │  ProfileValidator    │  Validate: GPA 0–4, IELTS 0–9, required fields
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐
 │  ProfileNormalizer   │  Normalize: master's → Master, AI → Artificial Intelligence
 └─────────┬───────────┘
           │
           ▼
 ┌─────────────────────┐    ┌──────────────────────────────────────────────┐
 │  Repository (L0)    │◄───│  PostgreSQL                                  │
 │                     │    │  SELECT s.* FROM scholarship s               │
 │  extraction_status  │    │  JOIN country c ON ...                       │
 │  = 'approved'       │    │  LEFT JOIN scholarship_requirement r ON ...  │
 │                     │    │  LEFT JOIN scholarship_benefit b ON ...      │
 │  Eager loads:       │    │  LEFT JOIN scholarship_timeline t ON ...     │
 │  country, req,      │    │  WHERE s.extraction_status = 'approved'      │
 │  benefit, timeline  │    │                                              │
 └─────────┬───────────┘    └──────────────────────────────────────────────┘
           │
           │  list[Scholarship] — all approved, eager-loaded
           │
           ▼
 ┌─────────────────────┐
 │  FilterEngine (L1)  │
 │                     │
 │  _not_expired:      │
 │  deadline >= today  │
 │  OR deadline IS NULL│
 │                     │
 │  Removed:           │
 │  • expired scholar- │
 │    ships            │
 └─────────┬───────────┘
           │
           │  list[Scholarship] — non-expired
           │
           ▼
 ┌─────────────────────┐
 │  ScoringEngine (L2) │
 │                     │
 │  For each:          │
 │  • country    (20)  │
 │  • degree     (20)  │
 │  • field      (20)  │
 │  • gpa        (15)  │
 │  • language   (10)  │
 │  • funding     (5)  │
 │  • research    (5)  │
 │  • work        (3)  │
 │  • leadership  (2)  │
 │  ─────────────────  │
 │  total      (100)   │
 └─────────┬───────────┘
           │
           │  list[(Scholarship, CriteriaScores)]
           │
           ▼
 ┌─────────────────────┐
 │  RankingEngine (L3) │
 │                     │
 │  Sort by:           │
 │  1. total score  ↓  │
 │  2. deadline     ↑  │
 │  3. funding type    │
 │  4. completeness    │
 │                     │
 │  Top-N: 10          │
 └─────────┬───────────┘
           │
           │  list[MatchResult] — top-10 ranked
           │
           ▼
 ┌─────────────────────┐
 │  ExplanationEngine  │
 │  (L4)               │
 │                     │
 │  For each result:   │
 │  • strengths        │
 │  • gaps             │
 │  • next steps       │
 │  • summary          │
 └─────────┬───────────┘
           │
           │  list[MatchResult + Explanation]
           │
           ▼
 ┌─────────────────────┐
 │  API Response       │
 └─────────────────────┘
```

## 7.2 FilterEngine Detail (L1)

```text
Input:  profile (UserProfile) — accepted for API consistency, not used in MVP
        scholarships (list[Scholarship]) — from L0

for each scholarship in scholarships:
    │
    └─ _not_expired(scholarship)
        ├─ timeline is NULL?
        │   └─ YES → include (no timeline data)
        ├─ deadline is NULL?
        │   └─ YES → include (open-ended)
        └─ deadline >= today?
            ├─ YES → include
            └─ NO  → exclude (expired)

Output: list[Scholarship] — non-expired only
```

## 7.3 ScoringEngine Detail (L2)

```text
Input:  profile (UserProfile)
        scholarship (Scholarship) — from L1

for each scholarship:
    │
    ├─ _score_country (20)
    │   ├─ country.name in profile.target_countries?
    │   │   ├─ YES → 20
    │   │   └─ NO  → 0
    │   └─ target_countries empty (any)? → 20
    │
    ├─ _score_degree (20)
    │   ├─ scholarship.degree in profile.target_degrees?
    │   │   ├─ YES → 20
    │   │   └─ NO  → 0
    │   └─ target_degrees empty (any)? → 20
    │
    ├─ _score_field (20)
    │   ├─ scholarship.field_of_study empty? → 20
    │   └─ overlap = |user_fields ∩ sch_fields|
    │       ├─ overlap > 0 → 20 * (overlap / |sch_fields|)
    │       └─ overlap = 0 → 0
    │
    ├─ _score_gpa (15)
    │   ├─ no minimum_gpa? → 15
    │   └─ 15 * min(profile.gpa / min_gpa, 1.0)
    │
    ├─ _score_language (10)
    │   ├─ ielts_required?
    │   │   └─ 10 * min(profile.ielts / min_ielts, 1.0)
    │   ├─ toefl_required?
    │   │   └─ 10 * min(profile.toefl / min_toefl, 1.0)
    │   └─ neither required? → 10
    │
    ├─ _score_funding (5)
    │   └─ funding_type == profile.funding_preference? → 5 : 0
    │
    ├─ _score_research (5)
    │   ├─ no requirement? → 5
    │   └─ ordinal comparison → 5, 2.5, or 0
    │
    ├─ _score_work (3)
    │   ├─ no requirement? → 3
    │   └─ ordinal comparison → 3, 1.5, or 0
    │
    └─ _score_leadership (2)
        └─ profile.leadership? → 2 : 0

    total = sum of all (0–100)

Output: CriteriaScores(total=...)
```

---

# 8. Filtering Flow Example

## 8.1 Profile

```python
profile = UserProfile(
    target_country="Japan",
    degree="Master",
    field_of_study=["Computer Science", "Artificial Intelligence"],
    current_gpa=3.5,
    ielts_score=7.0,
    research_experience="Preferred",
    work_experience="Optional",
    publication="Not Required",
    leadership=True,
    funding_preference="Fully Funded",
)
```

## 8.2 Candidate Scholarships

| # | Name | Degree | Country | Deadline | Fields | Status |
|---|------|--------|---------|----------|--------|--------|
| 1 | MEXT | Master | Japan | 2027-03-31 | CS, Engineering | approved |
| 2 | DAAD | Master | Germany | 2027-06-30 | CS | approved |
| 3 | JASSO | Bachelor | Japan | 2027-04-30 | CS | approved |
| 4 | MEXT Research | PhD | Japan | 2027-01-31 | CS, AI | approved |
| 5 | Toyota | Master | Japan | 2025-12-31 | Engineering | approved |
| 6 | Wellcome | Master | UK | 2027-08-31 | Medicine | approved |
| 7 | Pending | Master | Japan | 2027-05-31 | CS | pending_review |
| 8 | Open Math | Master | Japan | 2027-09-30 | Mathematics | approved |

## 8.3 Layer-by-Layer Execution

### L0: Repository

`WHERE extraction_status = 'approved'`

**Excluded:** #7 Pending (status = pending_review)

**Remaining (7):** MEXT, DAAD, JASSO, MEXT Research, Toyota, Wellcome, Open Math

### L1: FilterEngine

`_not_expired: deadline >= 2026-07-12 OR deadline IS NULL`

**Excluded:** #5 Toyota (deadline 2025-12-31, expired)

**Remaining (6):** MEXT, DAAD, JASSO, MEXT Research, Wellcome, Open Math

### L2: ScoringEngine

| # | Name | Country (20) | Degree (20) | Field (20) | GPA (15) | Lang (10) | Fund (5) | Res (5) | Work (3) | Lead (2) | **Total** |
|---|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | MEXT | 20 | 20 | 10¹ | 15² | 10³ | 5 | 5 | 3 | 2 | **90** |
| 2 | DAAD | 0 | 20 | 20 | 15 | 10 | 5 | 5 | 3 | 2 | **80** |
| 3 | JASSO | 20 | 0 | 20 | 15 | 10 | 5 | 5 | 3 | 2 | **80** |
| 4 | MEXT Research | 20 | 0 | 20 | 15 | 10 | 5 | 5 | 3 | 2 | **80** |
| 6 | Wellcome | 0 | 20 | 0 | 15 | 10 | 5 | 5 | 3 | 2 | **60** |
| 8 | Open Math | 20 | 20 | 0 | 15 | 10 | 5 | 5 | 3 | 2 | **80** |

¹ MEXT: 1/2 fields overlap (CS matches, Engineering doesn't) → 20 * 0.5 = 10
² All assume min_gpa ≤ 3.5 → full 15
³ All assume IELTS min ≤ 7.0 → full 10

### L3: RankingEngine

Sorted by total score (descending), tiebreak by deadline:

| Rank | Name | Score | Deadline |
|------|------|------:|----------|
| 1 | MEXT | 90 | 2027-03-31 |
| 2 | DAAD | 80 | 2027-06-30 |
| 3 | JASSO | 80 | 2027-04-30 |
| 4 | MEXT Research | 80 | 2027-01-31 |
| 5 | Open Math | 80 | 2027-09-30 |
| 6 | Wellcome | 60 | 2027-08-31 |

**Top-10 result:** All 6 (fewer than 10 available).

### L4: ExplanationEngine

**MEXT (90):** Strong match. Country, degree, funding, research, work, leadership all match. Field overlap is partial (CS but not Engineering).

**DAAD (80):** Strong match on criteria, but country mismatch (Germany vs Japan). User may want to consider if they're open to Germany.

**JASSO (80):** Strong match on criteria, but degree mismatch (Bachelor vs Master). Not applicable for postgraduate study.

**MEXT Research (80):** Strong match on criteria, but degree mismatch (PhD vs Master). Consider if PhD is of interest.

**Open Math (80):** Strong match on criteria, but no field overlap (Mathematics vs CS/AI). Consider if mathematics is relevant.

**Wellcome (60):** Moderate match. Country mismatch (UK) and no field overlap (Medicine). Low relevance.

---

# 9. Fields That Should NEVER Be Filters

| Field | Reason |
|-------|--------|
| `scholarship_name` | Display metadata. Not a matching signal. |
| `provider.provider_name` | Display metadata. Provider type preference is a future scoring criterion. |
| `university` | Optional field. Not all scholarships have one. Would exclude government scholarships. |
| `benefit.*` | Feature flags. Inform comparison, not eligibility. |
| `scholarship_version.*` | Audit history. Not relevant to matching. |
| `application_url`, `official_page_url` | Link metadata. |
| `source.source_name` | Display metadata. |
| `timeline.application_open` | Informational. User can set reminders. |
| `timeline.interview_date`, `result_date`, `study_start` | Informational timeline details. |
| `requirement.recommendation_letter`, `motivation_letter`, `cv_required`, `passport_required` | Application process requirements. Belong in gap analysis. |
| `requirement.age_limit` | Could be a mandatory filter when `UserProfile.date_of_birth` is added. Not in MVP. |
| `requirement.gre_required` | Could be a scoring criterion when `UserProfile.gre_score` is added. Not in MVP. |

---

# 10. Future Extensibility

## 10.1 Expected Additions by Milestone

| # | Criterion | Profile Field Change | Scholarship Field | Layer | Type | API Impact |
|---|-----------|---------------------|-------------------|-------|------|------------|
| X1 | IELTS Score | Already exists | `requirement.minimum_ielts` | L2 | Scoring (weight 10) | **None — already implemented** |
| X2 | TOEFL Score | Already exists | `requirement.minimum_toefl` | L2 | Scoring (weight 10) | **None — already implemented** |
| X3 | GRE Score | Add `gre_score: int \| None` | `requirement.minimum_gre` | L2 | Scoring Criterion | Add field to UserProfile. Add `_score_gre` to ScoringEngine. No FilterEngine change. |
| X4 | Nationality | Add `nationality: str` | (new field on requirement) | L2 | Scoring Criterion | Add field to UserProfile. Add `_score_nationality` to ScoringEngine. Some scholarships restrict by nationality — this is a scoring signal, not a filter. |
| X5 | Age | Add `date_of_birth: date` | `requirement.age_limit` | L1 | **Mandatory Filter** | Add `_meets_age_limit` to FilterEngine. Binary: over or under. First new predicate since deadline. FilterEngine signature unchanged. |
| X6 | Publications | Already exists | `requirement.publication` | L2 | Scoring Criterion | Add weight to ScoringEngine when ready. No FilterEngine change. |
| X7 | Multi-Country | Change `target_country: str` → `target_countries: list[str]` | `country.name` | L2 | Scoring Criterion | Update `_score_country` to handle list. Empty = any country. **No FilterEngine change** (country already in ScoringEngine). |
| X8 | Multi-Degree | Change `degree: str` → `target_degrees: list[str]` | `scholarship.degree` | L2 | Scoring Criterion | Update `_score_degree` to handle list. Empty = any degree. **No FilterEngine change** (degree already in ScoringEngine). |
| X9 | Provider Type | Add `preferred_providers: list[str]` | `provider.scholarship_type` | L2 | Scoring Criterion | Add `_score_provider_type` to ScoringEngine. No FilterEngine change. |
| X10 | University Pref | Add `preferred_universities: list[str]` | `university.name` | L2 | Scoring Criterion | Add `_score_university` to ScoringEngine. Soft preference. No FilterEngine change. |
| X11 | Scholarship Type | Add `preferred_types: list[str]` | `scholarship.scholarship_type` | L2 | Scoring Criterion | Add `_score_type` to ScoringEngine. No FilterEngine change. |

## 10.2 API Stability

The `FilterEngine.filter(profile, scholarships) -> list[Scholarship]` signature is stable across all planned extensions:

- **Adding a scoring criterion** (X3, X4, X6, X7, X8, X9, X10, X11): Changes ScoringEngine only. FilterEngine untouched.
- **Adding a mandatory filter** (X5): Adds a predicate to FilterEngine. Signature unchanged.
- **Moving a criterion between layers** (none planned): Would require FilterEngine changes but not signature changes.

## 10.3 Migration Path: Country/Degree to Multi-Select

When `target_country: str` becomes `target_countries: list[str]`:

1. Change `UserProfile.target_country` to `target_countries: list[str]`.
2. Update `ProfileValidator` to accept list.
3. Update `ProfileNormalizer` to normalize list entries.
4. Update `ScoringEngine._score_country` to check membership.
5. **FilterEngine: no change.** Country is already in ScoringEngine.

When `degree: str` becomes `target_degrees: list[str]`:

1. Same pattern as country.
2. **FilterEngine: no change.** Degree is already in ScoringEngine.

---

# 11. Implementation Impact

## 11.1 Files to Modify

| File | Change | Reason |
|------|--------|--------|
| `services/matching/filter/engine.py` | Remove `_matches_degree`, `_matches_country`, `_field_overlap`. Keep `_not_expired` only. | Country/Degree/Field moved to ScoringEngine. |
| `services/matching/filter/engine.py` | Update docstring to reflect single-predicate design. | Documentation accuracy. |
| `services/scholarship/repository.py` | No change needed. `get_all_approved()` already filters by `extraction_status`. | Already correct. |
| `services/matching/scoring/engine.py` | No change. `_score_country`, `_score_degree`, `_score_field` already implement scoring. | Already correct. |
| `scripts/verify_milestone_3_2.py` | Complete rewrite. Remove tests for degree/country/field filtering. Test only deadline filtering. | Test must match new FilterEngine scope. |
| `scripts/verify_milestone_3_3.py` | May need updates if scoring tests assumed pre-filtering. | Verify scoring handles 0-score cases. |

## 11.2 Implementation Order

1. Rewrite `services/matching/filter/engine.py` (single predicate).
2. Rewrite `scripts/verify_milestone_3_2.py` (deadline-only tests).
3. Run all verification scripts M3.1, M3.2, M3.3.
4. Fix any regressions in M3.3 scoring tests (scoring now handles zero-scored scholarships that were previously filtered out).

## 11.3 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| M3.3 scoring tests fail because scholarships with 0 country/degree/field scores now reach ScoringEngine | Medium | Low | ScoringEngine already handles 0 scores correctly. Tests may need updating if they assumed pre-filtered input. |
| User sees "irrelevant" scholarships (wrong country/degree) in results | Medium | Low | These rank at the bottom (60–80 vs 90–100). Top-N truncation naturally excludes them. ExplanationEngine explains why they rank low. |
| Performance: more scholarships reach ScoringEngine (no pre-filtering) | Low | Low | Scoring is O(1) per scholarship. Even 10,000 scholarships × 9 criteria = 90,000 simple operations. Not a concern. |

---

# Appendix A: Specification Conflict Resolution

| # | Conflict | Spec A | Spec B | Resolution |
|---|----------|--------|--------|------------|
| C1 | Country classification | Data Dictionary: weight 20 (Scoring) | Matching Engine Spec: Filter | **Data Dictionary governs.** Country is a Scoring Criterion (weight 20). |
| C2 | Degree classification | Data Dictionary: weight 20 (Scoring) | Matching Engine Spec: Filter | **Data Dictionary governs.** Degree is a Scoring Criterion (weight 20). |
| C3 | Field of Study classification | Data Dictionary: weight 20 (Scoring) | Matching Engine Spec: Filter ("Jurusan tidak tersedia") | **Data Dictionary governs.** Field is a Scoring Criterion (weight 20). "Jurusan tidak tersedia" refers to degree-level availability, not field overlap. |
| C4 | Work Experience weight | Data Dictionary: 5 | Matching Engine Spec: 3 | **Matching Engine Spec governs** (includes Leadership at 2). Data Dictionary omits Leadership. |
| C5 | Leadership | Matching Engine Spec: weight 2 | Data Dictionary: not listed | **Matching Engine Spec governs.** Leadership is a Scoring Criterion (weight 2). |
| C6 | Repository filtering | Repository Pattern: no business rules | extraction_status filter | **Documented exception.** extraction_status is data-governance, not business logic. Belongs at Repository level. |

---

# Appendix B: Decision Log

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|---------------------|
| D1 | Country → ScoringEngine | Data Dictionary weight 20. Eliminates Hard Filter + Scoring contradiction. | Hard Filter (v0.1): contradicts weight assignment. |
| D2 | Degree → ScoringEngine | Data Dictionary weight 20. Eliminates Hard Filter + Scoring contradiction. | Hard Filter (v0.1): contradicts weight assignment. |
| D3 | Field → ScoringEngine | Data Dictionary weight 20. Zero overlap = 0 points, ranks last. | Hard Filter (v0.1): redundant with scoring. |
| D4 | Deadline → FilterEngine (Mandatory) | Expired = objectively non-actionable. No user scenario wants expired results. | Scoring: would give 0 points but still show expired scholarships. |
| D5 | extraction_status → Repository | Data-governance gate. Not matching logic. Analogous to soft-delete pattern. | FilterEngine: would require all consumers to apply same filter. |
| D6 | Single-predicate FilterEngine | Only deadline qualifies as mandatory filter in MVP. Country/Degree/Field are scoring criteria. | Multi-predicate (v0.1): included criteria that are scoring, not filtering. |
