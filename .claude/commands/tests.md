# How to Write Tests

**Scope:** Step-by-step procedure for writing tests in Polaris.
**Tool:** pytest (see `docs/v0.1/tech-stack.md`)

---

## Test Philosophy

Test behavior, not implementation. Each test should verify that a specific requirement from the spec is met.

---

## What to Test

| Layer | What to Test |
|-------|-------------|
| Models | Column types, constraints, relationships, TimestampMixin |
| Pydantic Schemas | Validation rules, required fields, enum values, edge cases |
| Services | Core business logic, edge cases, error conditions |
| Connectors | Success fetch, error handling, retry behavior |
| Pipeline stages | Stage isolation, input/output contracts, failure handling |
| API Endpoints | Request validation, response shape, status codes |
| Matching Engine | Scoring accuracy, filtering correctness, ranking order |

---

## Directory Structure

```
tests/
├── conftest.py               # Shared fixtures
├── test_models/
│   └── test_scholarship.py
├── test_schemas/
│   └── test_scholarship_schema.py
├── test_services/
│   └── test_matching_engine.py
├── test_connectors/
│   └── test_mext_connector.py
├── test_pipeline/
│   └── test_extractor.py
└── test_api/
    └── test_scholarship_endpoints.py
```

---

## Procedure

### Step 1 — Identify What to Test

Map the test to a spec requirement. Each test should answer:

> "According to [spec section], does [component] produce [expected output] given [input]?"

### Step 2 — Write the Test

Basic test structure:

```python
def test_scholarship_filtering_excludes_wrong_degree():
    """Filtering must exclude scholarships that don't match degree.
    
    Ref: matching-engine-design-specification.md §Step 3
    """
    scholarships = [
        Scholarship(degree="Master", country="Japan"),
        Scholarship(degree="PhD", country="Japan"),
    ]
    
    result = filter_scholarships(
        scholarships,
        profile=UserProfile(degree="Master", target_country="Japan")
    )
    
    assert len(result) == 1
    assert result[0].degree == "Master"
```

### Step 3 — Write Fixtures

Reusable test data goes in `tests/conftest.py`:

```python
import pytest
from database.models.scholarship import Scholarship


@pytest.fixture
def sample_scholarship():
    return Scholarship(
        scholarship_id="TEST-001",
        scholarship_name="Test Scholarship",
        provider_id="PROV-001",
        country="Japan",
        degree="Master",
        funding_type="Fully Funded",
    )
```

### Step 4 — Test Database Models

Use a test database (SQLite in-memory for speed, PostgreSQL for integration):

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models.base import Base


@pytest.fixture(scope="session")
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s
        s.rollback()
```

### Step 5 — Test Pydantic Schemas

```python
import pytest
from pydantic import ValidationError
from schemas.scholarship import ScholarshipExtracted


def test_gpa_must_be_in_valid_range():
    """GPA must be between 0.00 and 4.00 per data-dictionary.md."""
    with pytest.raises(ValidationError):
        ScholarshipExtracted(minimum_gpa=5.0, ...)


def test_ielts_must_be_in_valid_range():
    """IELTS must be between 0.0 and 9.0 per data-dictionary.md."""
    with pytest.raises(ValidationError):
        ScholarshipExtracted(minimum_ielts=10.0, ...)
```

### Step 6 — Test API Endpoints

Use FastAPI's `TestClient`:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_scholarship_search_returns_filtered_results():
    response = client.get("/api/v1/scholarships/?country=Japan&degree=Master")
    assert response.status_code == 200
    data = response.json()
    assert all(s["country"] == "Japan" for s in data)
    assert all(s["degree"] == "Master" for s in data)
```

---

## Matching Engine Tests

The Matching Engine must be deterministic. Tests should verify:

- Same input always produces same output
- Weights sum to 100
- Country/Degree/Field match scores are correct
- Filtering correctly excludes ineligible scholarships
- Ranking order is consistent with score ordering

```python
def test_matching_score_is_deterministic():
    profile = UserProfile(country="Japan", degree="Master")
    scholarship = Scholarship(country="Japan", degree="Master")
    
    score1 = calculate_match_score(profile, scholarship)
    score2 = calculate_match_score(profile, scholarship)
    
    assert score1 == score2
```

---

## Rules

- Tests must reference the spec requirement they verify (in docstring or comment).
- No LLM calls in unit tests — mock the extractor boundary.
- No external HTTP calls — mock connector responses.
- Test both success and failure paths.
- Validator tests must cover all required fields and enum values.
- Test file names: `test_{module_name}.py`.
- Test function names: `test_{what}_{when}_{expected}`.

---

## Running Tests

```bash
pytest                          # All tests
pytest tests/test_models/       # Specific module
pytest -k "test_matching"       # By name pattern
pytest -v                       # Verbose output
```

---

## Anti-Patterns

- Tests that only test Python/Pydantic, not Polaris requirements
- No fixtures — data duplicated across tests
- Mocking internal implementation details
- Tests that depend on database state from other tests
- Testing the same behavior multiple times
- Tests with no docstring or spec reference

---

## References

- Data Dictionary (field validation rules): `docs/v0.1/data-dictionary.md`
- Matching weights: `docs/v0.1/matching-engine-design-specification.md`
- Tech stack (pytest): `docs/v0.1/tech-stack.md`
- Example extraction (valid data shape): `examples/scholarship-extraction.json`
