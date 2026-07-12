"""Shared fixtures for Polaris tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app
from database.models import Base
from database.session import get_engine


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create all database tables before running tests."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


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
