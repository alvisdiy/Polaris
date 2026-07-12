# Database Implementation Standards

**Scope:** Practical rules for implementing database models, migrations, and queries in Polaris.
**Does NOT replace:** `docs/v0.1/database-schema-specification.md` or `docs/v0.1/data-dictionary.md`.

---

## Stack

- **ORM:** SQLAlchemy 2 (mapped_column style)
- **Database:** PostgreSQL
- **Migrations:** Alembic
- **Driver:** psycopg (async-capable)

---

## Model Conventions

### Base Class

All models inherit from `database.models.base.Base`:

```python
from database.models.base import Base, TimestampMixin

class Scholarship(Base, TimestampMixin):
    __tablename__ = "scholarship"
    scholarship_id: Mapped[str] = mapped_column(String(32), primary_key=True)
```

### TimestampMixin

All tables MUST use `TimestampMixin` which provides:

- `created_at` — `DateTime(timezone=True)`, server default `now()`
- `updated_at` — `DateTime(timezone=True)`, server default `now()`, onupdate `now()`

### Naming

- Table names: `snake_case` (e.g., `scholarship_requirement`)
- Column names: `snake_case` (e.g., `minimum_gpa`)
- Primary keys: `{entity}_id` (e.g., `scholarship_id`)
- Foreign keys: `{related_entity}_id` (e.g., `provider_id`)
- Indexes: `ix_{table}_{column}`

### Types

| Data | SQLAlchemy Type | Example |
|------|----------------|---------|
| UUID/ID | `String(32)` or `UUID` | `SCH-000001` |
| Text | `String(N)` or `Text` | Varies |
| Boolean | `Boolean` | `True` |
| Number | `Float` or `Integer` | `3.25` |
| Enum | PostgreSQL ENUM or `String` | `Government` |
| Date | `Date` | `2027-05-31` |
| Timestamp | `DateTime(timezone=True)` | Auto via mixin |
| JSON | `JSONB` | Flexible metadata |

### Enum Handling

Use `String` columns with Pydantic validation rather than PostgreSQL ENUM types when possible. This avoids migration complexity for enum value changes.

```python
# Preferred — validated at application level
scholarship_type: Mapped[str] = mapped_column(String(20), nullable=False)

# Pydantic schema enforces valid values
class ScholarshipType(str, Enum):
    GOVERNMENT = "Government"
    UNIVERSITY = "University"
    FOUNDATION = "Foundation"
    NGO = "NGO"
    COMPANY = "Company"
```

### Relationships

Use SQLAlchemy 2 `relationship()` with explicit `foreign_keys` and `back_populates`:

```python
provider: Mapped["Provider"] = relationship(
    back_populates="scholarships",
    foreign_keys="[Scholarship.provider_id]",
)
```

---

## Migration Rules

### Creating a Migration

```bash
alembic revision --autogenerate -m "descriptive_message"
```

### Migration Checklist

- [ ] `target_metadata` in `database/migrations/env.py` points to `Base.metadata`
- [ ] Migration includes both `upgrade()` and `downgrade()`
- [ ] New columns have appropriate defaults or nullable settings
- [ ] No data loss in `upgrade()` without backup
- [ ] Foreign key constraints are explicit
- [ ] Indexes added for frequently queried columns

### Important

`database/migrations/env.py` currently has `target_metadata = None`. Before autogenerate can work, update it:

```python
from database.models.base import Base
target_metadata = Base.metadata
```

Also ensure all model modules are imported before migration runs.

---

## Query Patterns

### Session Management

Always use the session from `database/session.py`. Never create engines or sessions directly.

```python
from database.session import SessionLocal

def get_scholarships():
    with SessionLocal() as session:
        return session.execute(select(Scholarship)).scalars().all()
```

### Filtering

Use SQLAlchemy `select()` with explicit filters:

```python
stmt = select(Scholarship).where(
    Scholarship.country == country,
    Scholarship.degree == degree,
    Scholarship.application_deadline >= date.today(),
)
```

---

## Anti-Patterns

- Creating models without `TimestampMixin`
- Using `backref` instead of explicit `back_populates`
- Raw SQL when ORM provides the same functionality
- Session objects passed between module boundaries
- Auto-incrementing integer IDs for public-facing entities
- Hardcoded table names in queries
- Migrations that drop columns without `downgrade()`

---

## References

- Schema design: `docs/v0.1/database-schema-specification.md`
- Field definitions: `docs/v0.1/data-dictionary.md`
- Current model base: `database/models/base.py`
- Current session config: `database/session.py`
