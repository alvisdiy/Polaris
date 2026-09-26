"""Unit tests for GenericHTTPConnector."""

import uuid

import pytest

from services.ingestion.connectors import ConnectorConfig
from services.ingestion.connectors.generic_connector import GenericHTTPConnector

pytestmark = pytest.mark.unit


class TestGenericHTTPConnectorDiscovery:
    """Test link extraction and discovery logic."""

    def test_extract_candidate_links_basic(self):
        """Extract links with default scholarship keywords."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.org/scholarships",
        )
        connector = GenericHTTPConnector(config)

        html = """
        <html>
        <body>
            <a href="/scholarships/master-program">Master Scholarship</a>
            <a href="/about">About Us</a>
            <a href="/fellowships/phd">PhD Fellowship</a>
            <a href="https://external.com/grant">External</a>
        </body>
        </html>
        """

        base_url = "https://example.org/scholarships"
        candidates = connector.extract_candidate_links(html, base_url)

        assert "https://example.org/scholarships/master-program" in candidates
        assert "https://example.org/fellowships/phd" in candidates
        assert "https://example.org/about" not in candidates  # no keyword
        assert all("external.com" not in c for c in candidates)  # external domain

    def test_extract_candidate_links_custom_pattern(self):
        """Use custom regex pattern from config."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.org/funding",
            custom_settings={"url_pattern": r"/programs/\d+"},
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="/programs/123">Program 123</a>
        <a href="/programs/456">Program 456</a>
        <a href="/news/789">News</a>
        """

        candidates = connector.extract_candidate_links(html, "https://example.org/funding")

        assert "https://example.org/programs/123" in candidates
        assert "https://example.org/programs/456" in candidates
        assert "https://example.org/news/789" not in candidates

    def test_extract_candidate_links_multilingual_keywords(self):
        """Recognize German, French, Spanish, Indonesian keywords."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.de/",
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="/stipendium/master">German Stipendium</a>
        <a href="/bourse/phd">French Bourse</a>
        <a href="/beasiswa/sarjana">Indonesian Beasiswa</a>
        <a href="/contact">Contact</a>
        """

        candidates = connector.extract_candidate_links(html, "https://example.de/")

        assert "https://example.de/stipendium/master" in candidates
        assert "https://example.de/bourse/phd" in candidates
        assert "https://example.de/beasiswa/sarjana" in candidates
        assert "https://example.de/contact" not in candidates

    def test_extract_candidate_links_excludes_extensions(self):
        """Filter out images, CSS, JS, archives."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.org/",
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="/scholarship/apply">Apply</a>
        <a href="/images/logo.png">Logo</a>
        <a href="/styles/main.css">CSS</a>
        <a href="/scripts/app.js">JS</a>
        <a href="/files/form.zip">Form</a>
        """

        candidates = connector.extract_candidate_links(html, "https://example.org/")

        assert "https://example.org/scholarship/apply" in candidates
        assert all(".png" not in c for c in candidates)
        assert all(".css" not in c for c in candidates)
        assert all(".js" not in c for c in candidates)
        assert all(".zip" not in c for c in candidates)

    def test_extract_candidate_links_deduplication(self):
        """Deduplicate identical URLs and normalize fragments."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.org/",
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="/scholarship/apply">Apply</a>
        <a href="/scholarship/apply">Apply Again</a>
        <a href="/scholarship/apply#section1">With Fragment</a>
        """

        candidates = connector.extract_candidate_links(html, "https://example.org/")

        assert candidates.count("https://example.org/scholarship/apply") == 1

    def test_extract_candidate_links_subdomain_filtering(self):
        """Allow subdomains when configured."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://main.example.org/",
            custom_settings={"allow_subdomains": True},
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="https://main.example.org/scholarship">Main</a>
        <a href="https://portal.example.org/grant">Subdomain Portal</a>
        <a href="https://other.com/fellowship">External</a>
        """

        candidates = connector.extract_candidate_links(html, "https://main.example.org/")

        assert "https://main.example.org/scholarship" in candidates
        assert "https://portal.example.org/grant" in candidates
        assert all("other.com" not in c for c in candidates)

    def test_extract_candidate_links_no_subdomain(self):
        """Reject subdomains when allow_subdomains=False."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://main.example.org/",
            custom_settings={"allow_subdomains": False},
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="https://main.example.org/scholarship">Main</a>
        <a href="https://portal.example.org/grant">Subdomain Portal</a>
        """

        candidates = connector.extract_candidate_links(html, "https://main.example.org/")

        assert "https://main.example.org/scholarship" in candidates
        assert all("portal.example.org" not in c for c in candidates)

    def test_extract_candidate_links_exclude_patterns(self):
        """Apply custom exclusion patterns."""
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.org/",
            custom_settings={"exclude_patterns": [r"/news/", r"/blog/"]},
        )
        connector = GenericHTTPConnector(config)

        html = """
        <a href="/scholarship/master">Scholarship</a>
        <a href="/news/scholarship-announcement">News</a>
        <a href="/blog/fellowship-tips">Blog</a>
        """

        candidates = connector.extract_candidate_links(html, "https://example.org/")

        assert "https://example.org/scholarship/master" in candidates
        assert all("/news/" not in c for c in candidates)
        assert all("/blog/" not in c for c in candidates)
