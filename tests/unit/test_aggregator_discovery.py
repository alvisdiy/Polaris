from __future__ import annotations

from dataclasses import replace

import pytest

from services.aggregator_discovery.adapters import (
    AggregatorSource,
    discover_html_candidates,
    discover_html_source,
    discover_rss_candidates,
    load_aggregator_sources,
)

FULLY = AggregatorSource(
    id="fully_scholarships",
    name="Fully Scholarships",
    base_url="https://fullyscholarships.com/",
    discovery_urls=("https://fullyscholarships.com/fully-funded-scholarships/",),
    max_pages=3,
)
OC = AggregatorSource(
    id="opportunities_circle",
    name="Opportunities Circle",
    base_url="https://www.opportunitiescircle.com/",
    discovery_urls=("https://www.opportunitiescircle.com/scholarships/",),
    max_pages=3,
)


def test_config_starts_without_country_or_provider():
    sources = load_aggregator_sources()
    assert [source.id for source in sources] == ["fully_scholarships", "opportunities_circle"]
    assert all(not hasattr(source, "country_id") for source in sources)
    assert all(source.max_pages == 3 for source in sources)


def test_html_archive_discovers_and_deduplicates_canonical_article_urls():
    archive = "https://fullyscholarships.com/fully-funded-scholarships/"
    html = """
    <html><head><title>Fully Funded Scholarships</title></head><body>
      <h1>Scholarships</h1>
      <a href="/eiffel-excellence-scholarship-2027-in-france/?utm_source=mail">
        Eiffel Excellence Scholarship 2027 in France</a>
      <a href="https://www.fullyscholarships.com/eiffel-excellence-scholarship-2027-in-france/">
        Eiffel Excellence Scholarship 2027 in France</a>
      <a href="/online-courses/2027-data-science-course/">Online Course 2027</a>
      <a href="https://example.org/external-scholarship-2027">External Scholarship</a>
      <a href="/page/2/">2</a>
    </body></html>
    """
    results = discover_html_candidates(FULLY, {archive: html})
    assert len(results) == 1
    assert results[0].canonical_url == "https://fullyscholarships.com/eiffel-excellence-scholarship-2027-in-france"
    # Metadata-only classification is recorded for downstream inspection; it
    # is not authoritative enough to reject a candidate before article fetch.
    assert results[0].page_intent in {"SCHOLARSHIP_DETAIL", "SCHOLARSHIP_OVERVIEW", "UNKNOWN"}
    assert results[0].discovered_from == archive


@pytest.mark.asyncio
async def test_html_adapter_follows_only_bounded_pagination():
    first = OC.discovery_urls[0]
    second = "https://www.opportunitiescircle.com/scholarships/page/2/"
    pages = {
        first: (
            '<a href="/university-of-twente-scholarship-2027/">University of Twente Scholarship 2027</a>'
            '<a href="/scholarships/page/2/">Next</a>'
        ),
        second: (
            '<a href="/open-doors-russian-scholarship/">Open Doors Russian Scholarship</a>'
            '<a href="/scholarships/page/3/">Next</a>'
        ),
    }
    fetched = []

    async def fake_fetch(url):
        fetched.append(url)
        return pages[url]

    results = await discover_html_source(replace(OC, max_pages=2), fake_fetch)
    assert fetched == [first, second]
    assert {candidate.title for candidate in results} == {
        "University of Twente Scholarship 2027",
        "Open Doors Russian Scholarship",
    }
    assert all(candidate.source_id == "opportunities_circle" for candidate in results)


def test_rss_and_atom_entries_are_parsed_and_deduplicated():
    rss = """<rss version="2.0"><channel>
      <item><title>Open Doors Russian Scholarship 2027</title><link>https://www.opportunitiescircle.com/open-doors-russian-scholarship/?utm_campaign=x</link></item>
      <item><title>Open Doors Russian Scholarship 2027</title><link>https://www.opportunitiescircle.com/open-doors-russian-scholarship/</link></item>
    </channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Open Doors Russian Scholarship 2027</title><link
        href="https://www.opportunitiescircle.com/open-doors-russian-scholarship/" />
    </entry></feed>"""
    rss_results = discover_rss_candidates(OC, rss, "https://www.opportunitiescircle.com/feed/")
    atom_results = discover_rss_candidates(OC, atom, "https://www.opportunitiescircle.com/feed/atom/")
    assert len(rss_results) == len(atom_results) == 1
    assert rss_results[0].canonical_url == atom_results[0].canonical_url
    assert rss_results[0].discovery_method == "rss"


def test_invalid_feed_reports_parse_failure():
    with pytest.raises(ValueError, match="Invalid RSS/Atom"):
        discover_rss_candidates(OC, "<rss>", "https://www.opportunitiescircle.com/feed/")
