"""Link discovery labels each organization by its own domain, not the surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.ingestion.ecosystem_strategies.link_discovery import (
    GovernmentStrategy,
    ScholarshipAgencyStrategy,
)


@pytest.fixture
def country():
    country = MagicMock()
    country.country_id = uuid4()
    country.iso2 = "JP"
    return country


async def _discover(strategy, links):
    connector = AsyncMock()
    connector.discover.return_value = links
    with patch(
        "services.ingestion.ecosystem_strategies.link_discovery.GenericPlaywrightConnector",
        return_value=connector,
    ):
        return await strategy.discover()


@pytest.mark.asyncio
async def test_a_ministry_surface_labels_a_university_as_university(country):
    strategy = GovernmentStrategy(
        country,
        "https://www.mext.go.jp/en/",
        allowed_tlds=[".go.jp", ".ac.jp"],
    )

    orgs = await _discover(
        strategy,
        [
            "https://www.mext.go.jp/en/",
            "https://www.u-tokyo.ac.jp/en/",
            "https://www.keio.ac.jp/en/",
        ],
    )

    by_url = {org.official_url: org.organization_type for org in orgs}
    assert by_url["https://www.mext.go.jp/en/"] == "Government"
    assert by_url["https://www.u-tokyo.ac.jp/en/"] == "University"
    assert by_url["https://www.keio.ac.jp/en/"] == "University"


@pytest.mark.asyncio
async def test_an_agency_surface_labels_a_ministry_as_government(country):
    strategy = ScholarshipAgencyStrategy(
        country,
        "https://www.jasso.go.jp/en/",
        allowed_tlds=[".go.jp", ".ac.jp"],
    )

    orgs = await _discover(
        strategy,
        [
            "https://www.mext.go.jp/en/",
            "https://www.jasso.go.jp/en/",
        ],
    )

    by_url = {org.official_url: org.organization_type for org in orgs}
    assert by_url["https://www.mext.go.jp/en/"] == "Government"
    # The surface's own organization keeps the configured type: JASSO is an
    # agency on a .go.jp host, not a ministry.
    assert by_url["https://www.jasso.go.jp/en/"] == "Scholarship Agency"


@pytest.mark.asyncio
async def test_an_unrecognised_domain_falls_back_to_the_surface_type(country):
    strategy = ScholarshipAgencyStrategy(
        country,
        "https://www.daad.de/en/",
        allowed_tlds=[".de"],
    )

    orgs = await _discover(strategy, ["https://www.example-stiftung.de/"])

    assert orgs[0].organization_type == "Foundation"


@pytest.mark.asyncio
async def test_one_provider_per_registered_domain(country):
    strategy = GovernmentStrategy(
        country,
        "https://www.mext.go.jp/en/",
        allowed_tlds=[".ac.jp"],
    )

    orgs = await _discover(
        strategy,
        [
            "https://www.u-tokyo.ac.jp/en/",
            "https://www.u-tokyo.ac.jp/en/admissions/",
            "https://www.u-tokyo.ac.jp/en/research/",
        ],
    )

    assert len(orgs) == 1
    assert orgs[0].official_url == "https://www.u-tokyo.ac.jp/en/"
