"""Shared fixtures for Polaris tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from api.app import app
from database.models import Base
from database.session import SessionLocal, get_engine


def pytest_collection_modifyitems(config, items):
    """Skip tests that need the development knowledge base.

    Golden samples, pinned discovery captures and the 41-record catalogue live
    in the development database, not in a fresh one. Those tests are valuable
    and must keep running where the data exists; on a clean CI database they
    would fail for a reason that says nothing about the code.

    Set ``POLARIS_RUN_DATA_TESTS=1`` to run them against a database that has
    the knowledge base.
    """
    if os.getenv("POLARIS_RUN_DATA_TESTS", "").strip() == "1":
        return
    skip = pytest.mark.skip(
        reason=(
            "requires the development knowledge base "
            "(set POLARIS_RUN_DATA_TESTS=1 to run against it)"
        )
    )
    for item in items:
        if "data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create and seed tables in the explicitly configured disposable test database."""
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


ADMIN_TEST_TOKEN = "test-admin-token"


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    """Every test runs with the admin token configured.

    Auth tests delete it explicitly. Without this, the review API correctly
    answers 503 and every curation test fails at the auth layer instead of
    the behaviour it is testing.
    """
    monkeypatch.setenv("POLARIS_ADMIN_TOKEN", ADMIN_TEST_TOKEN)


@pytest.fixture
def client():
    """FastAPI test client with the admin bearer token attached."""
    test_client = TestClient(app)
    test_client.headers.update({"Authorization": f"Bearer {ADMIN_TEST_TOKEN}"})
    return test_client


# Exposed to every test module rather than imported by each one: an import
# whose only purpose is fixture registration is invisible to linters, and
# removing it breaks the tests silently. Tests that curate records need this
# because the review API commits on its own.
from tests.integration._exploration_isolation import (  # noqa: E402,F401
    exploration_session,
)


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
