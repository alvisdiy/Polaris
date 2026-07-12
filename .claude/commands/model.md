# How to Implement SQLAlchemy Models

**Scope:** Step-by-step procedure for creating database models in Polaris.

---

## Prerequisites

- [ ] Read `docs/v0.1/database-schema-specification.md` for table structure
- [ ] Read `docs/v0.1/data-dictionary.md` for field definitions and types
- [ ] Review `database/models/base.py` for Base and TimestampMixin

---

## Procedure

### Step 1 — Identify Table Structure

From the Database Schema Specification, determine:

- Table name
- Primary key
- Columns and their types
- Foreign keys and relationships
- Cascade rules
- Required indexes

### Step 2 — Create Model File

Location: `database/models/{entity_name}.py`

Template:

```python
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin


class Scholarship(Base, TimestampMixin):
    __tablename__ = "scholarship"

    # Primary key
    scholarship_id: Mapped[str] = mapped_column(
        String(32), primary_key=True
    )

    # Required fields
    scholarship_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("provider.provider_id"), nullable=False
    )

    # Optional fields
    university_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("university.university_id"), nullable=True
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(
        back_populates="scholarships"
    )
```

### Step 3 — Map Types from Data Dictionary

| Data Dictionary Type | SQLAlchemy Type |
|---------------------|----------------|
| UUID | `String(32)` |
| String | `String(N)` |
| Enum | `String(20)` — validate with Pydantic |
| Float | `Float` |
| Integer | `Integer` |
| Boolean | `Boolean` |
| Date | `Date` |
| URL | `String(2048)` |
| Array | `JSONB` or separate table |

### Step 4 — Define Relationships

Follow the Entity Relationship section of the Database Schema Specification:

- **1:N** — ForeignKey on the "many" side, `relationship()` on both sides with `back_populates`
- **1:1** — ForeignKey + `uselist=False` on relationship

```python
# 1:N — Provider has many Scholarships
class Provider(Base, TimestampMixin):
    __tablename__ = "provider"
    provider_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scholarships: Mapped[list["Scholarship"]] = relationship(
        back_populates="provider"
    )
```

### Step 5 — Register in `__init__.py`

Update `database/models/__init__.py`:

```python
from .base import Base, TimestampMixin
from .scholarship import Scholarship
from .provider import Provider
```

### Step 6 — Create Migration

Follow `commands/migration.md` to generate and apply the migration.

---

## Rules

- Every model inherits `Base` and `TimestampMixin`.
- Use `mapped_column` style (SQLAlchemy 2), not legacy `Column()`.
- Field names match `docs/v0.1/data-dictionary.md` exactly.
- Use `String` columns for enums, validate at application layer with Pydantic.
- Primary keys follow `{entity}_id` naming.
- Foreign keys follow `{related_entity}_id` naming.
- Use `Optional[type]` for nullable columns, plain `type` for non-nullable.
- Cascade rules follow the Database Schema Specification:
  - Delete Provider → RESTRICT (do not cascade to scholarship)
  - Delete Source → RESTRICT
  - Delete Scholarship → CASCADE to requirement, benefit, timeline; NOT to version history

---

## Anti-Patterns

- Skipping `TimestampMixin`
- Using `Column()` instead of `mapped_column()`
- Using `backref` instead of explicit `back_populates`
- Guessing field names instead of checking the Data Dictionary
- Putting business logic in model classes
- Using PostgreSQL ENUM types (use String + Pydantic validation)
- Integer auto-increment PKs for public entities

---

## References

- Base and mixin: `database/models/base.py`
- Schema spec: `docs/v0.1/database-schema-specification.md`
- Data Dictionary: `docs/v0.1/data-dictionary.md`
- Migration procedure: `.claude/commands/migration.md`
- Database conventions: `.claude/context/database.md`
