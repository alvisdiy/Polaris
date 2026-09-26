"""Shared fixtures for Polaris tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app
from database.models import Base
from database.session import get_engine, SessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create all database tables before running tests."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    from scripts.seed_source_registry import seed_data
    seed_data()

    yield
    # Do not drop the shared PostgreSQL schema: it may contain the verified
    # knowledge base used by local end-to-end checks. Tests that create rows
    # must isolate them with their own transaction or cleanup fixture.


@pytest.fixture
def session():
    """Database session for tests.

    Each test gets a fresh session. Teardown rolls back to avoid contamination.
    """
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def rollback_session():
    """Session in an outer transaction that is always rolled back.

    Needed when the code under test commits on its own (durable run-level
    work). Binding the session to a connection with
    ``join_transaction_mode="create_savepoint"`` turns those inner commits into
    savepoint releases, so nothing reaches the shared development database.
    Plain ``session`` cannot do this: its rollback only discards work that was
    never committed, and committed test rows then change later runs.
    """
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    s = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_request():
    """Valid recommendation request payload."""
    return {
        "target_country": "Japan",
        "degree": "Master",
        "field_of_study": ["Computer Science"],
        "current_gpa": 3.5,
        "ielts_score": 7.0,
        "research_experience": "Preferred",
        "work_experience": "Optional",
        "publication": "Not Required",
        "leadership": True,
        "funding_preference": "Fully Funded",
    }
