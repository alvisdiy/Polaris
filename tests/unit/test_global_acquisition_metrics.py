"""Unit tests for global acquisition metrics reporting.

Tests that the acquisition script produces useful per-source metrics
as specified in the product requirements.
"""

import pytest

from services.ingestion.discovery import DiscoveryMetrics
from services.ingestion.country_orchestrator import CountryDiscoveryReport

pytestmark = pytest.mark.unit


class TestDiscoveryMetricsReporting:
    """Test DiscoveryMetrics captures all required fields."""

    def test_discovery_metrics_has_all_required_fields(self):
        """DiscoveryMetrics must track all fields needed for reporting."""
        from uuid import uuid4
        from datetime import datetime, timezone

        source_id = uuid4()
        metrics = DiscoveryMetrics(source_id=source_id)

        # Required fields for acquisition reporting
        assert hasattr(metrics, "candidate_urls_found")
        assert hasattr(metrics, "urls_after_filter")
        assert hasattr(metrics, "urls_already_seen")
        assert hasattr(metrics, "fetch_succeeded")
        assert hasattr(metrics, "fetch_failed")
        assert hasattr(metrics, "extraction_succeeded")
        assert hasattr(metrics, "extraction_failed")
        assert hasattr(metrics, "persisted")
        assert hasattr(metrics, "duplicates_skipped")
        assert hasattr(metrics, "errors")

        # Initial values
        assert metrics.candidate_urls_found == 0
        assert metrics.urls_after_filter == 0
        assert metrics.urls_already_seen == 0
        assert metrics.fetch_succeeded == 0
        assert metrics.fetch_failed == 0
        assert metrics.extraction_succeeded == 0
        assert metrics.extraction_failed == 0
        assert metrics.persisted == 0
        assert metrics.duplicates_skipped == 0
        assert metrics.errors == []

    def test_discovery_metrics_to_dict_includes_all_fields(self):
        """to_dict() must serialize all metrics fields."""
        from uuid import uuid4

        source_id = uuid4()
        metrics = DiscoveryMetrics(source_id=source_id)
        metrics.candidate_urls_found = 10
        metrics.urls_after_filter = 8
        metrics.urls_already_seen = 2
        metrics.fetch_succeeded = 5
        metrics.extraction_succeeded = 3
        metrics.persisted = 2

        result = metrics.to_dict()

        assert result["source_id"] == str(source_id)
        assert result["candidate_urls_found"] == 10
        assert result["urls_after_filter"] == 8
        assert result["urls_already_seen"] == 2
        assert result["fetch_succeeded"] == 5
        assert result["extraction_succeeded"] == 3
        assert result["persisted"] == 2


class TestCountryDiscoveryReport:
    """Test CountryDiscoveryReport aggregates per-source metrics."""

    def test_country_report_aggregates_per_source_metrics(self):
        """CountryDiscoveryReport must store per-source DiscoveryMetrics."""
        from uuid import uuid4

        source_id = uuid4()
        report = CountryDiscoveryReport(country_iso2="JP")

        # Add metrics for a source
        metrics = DiscoveryMetrics(source_id=source_id)
        metrics.candidate_urls_found = 15
        metrics.persisted = 3

        report.per_source_metrics["MEXT"] = metrics
        report.total_candidates = 15
        report.total_persisted = 3

        assert "MEXT" in report.per_source_metrics
        assert report.per_source_metrics["MEXT"].candidate_urls_found == 15
        assert report.per_source_metrics["MEXT"].persisted == 3

    def test_country_report_to_dict_includes_per_source(self):
        """to_dict() must include per_source_metrics."""
        from uuid import uuid4

        source_id = uuid4()
        report = CountryDiscoveryReport(country_iso2="KR")

        metrics = DiscoveryMetrics(source_id=source_id)
        report.per_source_metrics["GKS"] = metrics

        result = report.to_dict()

        assert "per_source_metrics" in result
        assert "GKS" in result["per_source_metrics"]
        assert result["per_source_metrics"]["GKS"]["source_id"] == str(source_id)


class TestValidationContract:
    """Test that validation requirements match database requirements."""

    def test_scholarship_type_not_in_database_schema(self):
        """scholarship_type is validated but not stored - document this gap."""
        from database.models.scholarship import Scholarship
        from sqlalchemy import inspect

        # Get all column names from Scholarship model
        mapper = inspect(Scholarship)
        column_names = [c.key for c in mapper.columns]

        # scholarship_type should NOT be in the database schema
        assert "scholarship_type" not in column_names
        # But these required fields ARE in the schema
        assert "scholarship_name" in column_names
        assert "degree" in column_names
        assert "funding_type" in column_names

    def test_validator_allows_optional_scholarship_type(self):
        """Validator allows scholarship_type to be None to preserve data integrity.

        Extraction is incomplete when the source doesn't clearly indicate the
        scholarship type. Rather than fabricate a value, we allow it to be None.
        Downstream matching and user review can handle the incomplete data.
        """
        from services.ingestion.validator import validate
        from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship

        # Create an extraction with scholarship_type=None – should be allowed
        extraction = ExtractedDocument(
            document_id="test-1",
            source_url="https://example.org",
            scholarship=ExtractedScholarship(
                scholarship_name="Test Scholarship",
                provider_name="Test Provider",
                scholarship_type=None,  # Optional – not fabricated
                country="Japan",
                degree=None,  # Also optional
                funding_type=None,  # Also optional
                application_url="https://example.org/apply",
                official_source="https://example.org",
            ),
        )
        # Validate should pass (None values are acceptable)
        report = validate(extraction)
        assert report.is_valid, f"Validation failed: {report.issues}"
