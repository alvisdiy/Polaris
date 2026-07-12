# How to Implement FastAPI Endpoints

**Scope:** Step-by-step procedure for creating API endpoints in Polaris.

---

## Prerequisites

- [ ] Feature is defined in a spec document
- [ ] Database models exist (see `commands/model.md`)
- [ ] Pydantic schemas are defined for request/response

---

## Procedure

### Step 1 — Define Pydantic Schemas

Create request and response schemas in the module's `schemas.py`:

```python
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ScholarshipResponse(BaseModel):
    scholarship_id: str
    scholarship_name: str
    provider_name: str
    country: str
    degree: str
    funding_type: str
    application_deadline: date
    official_source: str

    model_config = {"from_attributes": True}


class ScholarshipSearchRequest(BaseModel):
    country: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    funding_type: Optional[str] = None
```

### Step 2 — Implement Service

Business logic goes in the module's `service.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.scholarship import Scholarship


def search_scholarships(
    session: Session,
    country: str | None = None,
    degree: str | None = None,
) -> list[Scholarship]:
    stmt = select(Scholarship)
    if country:
        stmt = stmt.where(Scholarship.country == country)
    if degree:
        stmt = stmt.where(Scholarship.degree == degree)
    return list(session.execute(stmt).scalars().all())
```

### Step 3 — Create Router

Create the module's `router.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .schemas import ScholarshipResponse, ScholarshipSearchRequest
from .service import search_scholarships

router = APIRouter(prefix="/api/v1/scholarships", tags=["scholarships"])


@router.get("/", response_model=list[ScholarshipResponse])
def list_scholarships(
    params: ScholarshipSearchRequest = Depends(),
    session: Session = Depends(get_session),
):
    return search_scholarships(
        session=session,
        country=params.country,
        degree=params.degree,
    )
```

### Step 4 — Register Router

In the main application:

```python
from fastapi import FastAPI
from module.router import router

app = FastAPI(title="Polaris API")
app.include_router(router)
```

### Step 5 — Test the Endpoint

Use Swagger UI at `/docs` or tools like Bruno/Postman (see `docs/v0.1/tech-stack.md`).

---

## API Conventions

### URL Structure

```
/api/v1/{resource}          # Collection
/api/v1/{resource}/{id}     # Single item
/api/v1/{resource}/{id}/{sub}  # Sub-resource
```

### HTTP Methods

| Method | Purpose |
|--------|---------|
| `GET` | Read data |
| `POST` | Create new resource |
| `PUT` | Full update |
| `PATCH` | Partial update |
| `DELETE` | Remove resource |

### Response Codes

| Code | When |
|------|------|
| `200` | Successful read or update |
| `201` | Successful creation |
| `400` | Invalid input |
| `404` | Resource not found |
| `422` | Validation error (auto by FastAPI) |
| `500` | Unexpected server error |

### Versioning

All endpoints are prefixed with `/api/v1/`. Version bump only on breaking changes.

---

## Rules

- Route handlers are thin: parse request → call service → return response.
- All request input validated by Pydantic schemas.
- All response data shaped by Pydantic response models.
- Use `Depends()` for session injection.
- Use `response_model` on every endpoint.
- Never expose internal model fields (like `updated_at`) unless needed.
- Never put business logic in route handlers.

---

## Session Dependency

Create a dependency function for session management:

```python
from collections.abc import Generator

from sqlalchemy.orm import Session

from database.session import SessionLocal


def get_session() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
```

---

## Anti-Patterns

- Business logic in route handlers
- Returning raw SQLAlchemy models without response schema
- Manual JSON serialization instead of Pydantic
- Hardcoded response data
- Missing `response_model` on endpoints
- Catching all exceptions in routes

---

## References

- Architecture: `.claude/context/architecture.md`
- Coding standards: `.claude/context/coding-standards.md`
- Database conventions: `.claude/context/database.md`
- Tech stack: `docs/v0.1/tech-stack.md`
