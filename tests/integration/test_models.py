"""Tests for database ORM models (M1)."""

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.session import SessionLocal

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session():
    return SessionLocal()


class TestORMRelationships:
    """Test ORM relationships between Country, Provider, University."""

    def test_country_provider_relationship(self, db_session):
        """Country -> Provider back-reference works."""
        # Find Japan (seeded data)
        country = db_session.query(Country).filter_by(name="Japan").first()
        if not country:
            pytest.skip("Japan not seeded")

        # Should have at least one provider
        assert len(country.providers) > 0

    def test_provider_country_relationship(self, db_session):
        """Provider -> Country forward reference works."""
        provider = db_session.query(Provider).first()
        if not provider:
            pytest.skip("No providers seeded")

        assert provider.country is not None
        assert provider.country.name

    def test_country_university_relationship(self, db_session):
        """Country -> University back-reference works."""
        country = db_session.query(Country).filter_by(name="Japan").first()
        if not country:
            pytest.skip("Japan not seeded")

        # May or may not have universities
        assert isinstance(country.universities, list)
