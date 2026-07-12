# Coding Standards

**Scope:** Naming conventions, typing, imports, error handling, and code organization for Polaris.
**Single responsibility:** Define HOW code is written, not WHAT it does.

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules/files | `snake_case` | `matching_engine.py` |
| Classes | `PascalCase` | `MatchingEngine` |
| Functions | `snake_case` | `calculate_match_score()` |
| Variables | `snake_case` | `scholarship_count` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Private | `_prefix` | `_normalize_field()` |
| DB tables | `snake_case` | `scholarship_requirement` |
| DB columns | `snake_case` | `minimum_gpa` |
| Pydantic models | `PascalCase` | `ScholarshipCreate` |
| API routes | `kebab-case` | `/api/v1/scholarships` |
| Env vars | `UPPER_SNAKE_CASE` | `DATABASE_URL` |

---

## Python Version and Typing

**Target:** Python 3.13

- Use type hints on all function signatures.
- Use `Mapped[]` for SQLAlchemy columns.
- Use `Pydantic BaseModel` for request/response schemas.
- Use `from __future__ import annotations` where forward references are needed.

```python
# Good
def calculate_score(profile: UserProfile, scholarship: Scholarship) -> float: ...

# Bad
def calculate_score(profile, scholarship):
```

---

## Import Order

1. Standard library
2. Third-party packages
3. Local modules

Group with blank lines between each section. Use absolute imports.

```python
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from database.models.scholarship import Scholarship
from database.session import get_session
```

---

## Error Handling

### Application Errors

Define domain-specific exceptions in the module that owns them:

```python
class ConnectorError(Exception):
    """Raised when a connector fails to fetch content."""
    def __init__(self, source_id: str, reason: str):
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Connector failed for {source_id}: {reason}")
```

### Rules

- Never catch `Exception` broadly without re-raising or logging.
- Connector failures must NOT stop the pipeline — log and continue.
- Validation errors use Pydantic's built-in error reporting.
- Database errors are handled at the session/transaction boundary.

---

## Logging

Use `loguru` (per tech-stack spec):

```python
from loguru import logger

logger.info("Crawling source: {}", source_id)
logger.warning("Retry {}/{} for {}", attempt, max_retries, url)
logger.error("Connector failed: {}", error, exc_info=True)
```

### Log Levels

| Level | When |
|-------|------|
| `DEBUG` | Detailed diagnostic info |
| `INFO` | Normal operations (crawl started, extraction complete) |
| `WARNING` | Recoverable issues (retry needed, degraded quality) |
| `ERROR` | Failures requiring attention (connector down, validation failed) |

---

## File Organization

### Module Structure

```
module/
├── __init__.py      # Public API only (exports, no logic)
├── models.py        # SQLAlchemy models (if module owns tables)
├── schemas.py       # Pydantic schemas
├── service.py       # Business logic
├── router.py        # FastAPI routes
└── exceptions.py    # Module-specific errors (only if needed)
```

### `__init__.py` Rules

- Export public classes and functions only.
- No business logic.
- No side effects on import.

```python
# Good
from .service import MatchingEngine
from .schemas import MatchRequest, MatchResponse

# Bad
from .service import MatchingEngine, _internal_helper, engine_instance
```

---

## Dependency Rules

- See `docs/v0.1/tech-stack.md` for approved dependencies.
- Never add a new dependency without justification.
- Prefer stdlib first: `json` over `ujson`, `pathlib` over `os.path`, `logging` alternatives only if justified.
- Pin versions in requirements (not in pyproject.toml dev dependencies).

---

## Code Organization

### API Layer (`router.py`)

- Thin handlers only: parse request, call service, return response.
- No business logic in routes.
- Use dependency injection for sessions and services.

### Service Layer (`service.py`)

- All business logic lives here.
- Pure functions where possible.
- Dependencies injected, not imported globally.

### Model Layer (`models.py`)

- SQLAlchemy models with mapped_column style.
- Relationships defined explicitly.
- No business logic in models.

---

## Formatting

- **Linter:** Ruff
- **Formatter:** Black
- **Import sorting:** isort
- **Type checking:** mypy

Run before committing:

```bash
ruff check .
black .
isort .
mypy .
```

---

## Anti-Patterns

- Business logic in API route handlers
- Global mutable state
- Functions longer than 50 lines without clear justification
- Catching all exceptions silently
- `import *`
- Circular imports
- Hardcoded strings that should be constants or config
- Logging inside `__init__.py`
