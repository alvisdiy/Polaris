# How to Create Database Migrations

**Scope:** Step-by-step procedure for creating and managing Alembic migrations in Polaris.

---

## Prerequisites

- [ ] PostgreSQL is running and accessible
- [ ] `DATABASE_URL` is set in `.env` (see `.env.example`)
- [ ] Model changes are complete in `database/models/`
- [ ] All models are imported in the autogenerate target

---

## Setup (First Time)

Before autogenerate works, update `database/migrations/env.py`:

```python
from database.models.base import Base
# Import all model modules here so they register with Base.metadata
target_metadata = Base.metadata
```

This is a one-time fix. The current `env.py` has `target_metadata = None`.

---

## Procedure

### Step 1 — Verify Model

Confirm the model:

- Uses `Base` from `database.models.base`
- Uses `TimestampMixin`
- Has correct column types per `docs/v0.1/data-dictionary.md`
- Has correct relationships per `docs/v0.1/database-schema-specification.md`

### Step 2 — Generate Migration

```bash
alembic revision --autogenerate -m "add_scholarship_table"
```

Naming convention for messages:

| Change | Message Pattern |
|--------|----------------|
| New table | `add_{table_name}_table` |
| New column | `add_{column}_to_{table}` |
| Remove column | `remove_{column}_from_{table}` |
| Modify column | `modify_{column}_in_{table}` |
| Add index | `add_{index_name}_index` |
| Add constraint | `add_{constraint}_to_{table}` |

### Step 3 — Review Generated Migration

Open the generated file in `database/migrations/versions/` and verify:

- [ ] `upgrade()` creates exactly the intended change
- [ ] `downgrade()` cleanly reverses the change
- [ ] Column types are correct
- [ ] Nullable settings are correct
- [ ] Server defaults are set where needed
- [ ] Foreign keys reference correct tables and columns
- [ ] No unintended changes from autogenerate

### Step 4 — Apply Migration

```bash
# Apply
alembic upgrade head

# Verify
alembic current
```

### Step 5 — Test Rollback

```bash
# Roll back one revision
alembic downgrade -1

# Re-apply
alembic upgrade head
```

---

## Rules

- Every migration must have both `upgrade()` and `downgrade()`.
- Never edit a migration that has already been applied to shared environments.
- Never drop columns or tables without data backup consideration.
- Migration names are descriptive, not auto-generated slugs.
- All new tables must include `created_at` and `updated_at` via `TimestampMixin`.
- Cascade rules follow `docs/v0.1/database-schema-specification.md` — deleting a provider MUST NOT delete scholarships.

---

## Common Patterns

### Adding a Required Column to Existing Table

```python
def upgrade():
    op.add_column('scholarship', sa.Column('status', sa.String(20), nullable=True))
    op.execute("UPDATE scholarship SET status = 'active'")
    op.alter_column('scholarship', 'status', nullable=False)

def downgrade():
    op.drop_column('scholarship', 'status')
```

### Adding an Index

```python
def upgrade():
    op.create_index('ix_scholarship_country', 'scholarship', ['country'])

def downgrade():
    op.drop_index('ix_scholarship_country')
```

---

## Anti-Patterns

- Applying migrations without reviewing the generated code
- Skipping `downgrade()` implementation
- Editing applied migrations
- Manual DDL instead of Alembic
- Autogenerate without importing all models
- Dropping tables in migrations without confirmation

---

## References

- Database conventions: `.claude/context/database.md`
- Schema spec: `docs/v0.1/database-schema-specification.md`
- Alembic config: `alembic.ini`
- Migration env: `database/migrations/env.py`
