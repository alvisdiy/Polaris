"""Third-party aggregators are discovery leads, never official sources."""

from __future__ import annotations

import pytest

from services.domain.source_trust import (
    aggregator_host,
    blocked_source_host,
    host_of,
    is_aggregator_host,
    is_blocked_source_host,
)


class TestHostParsing:
    def test_strips_www_and_lowercases(self):
        assert host_of("https://WWW.Example.ORG/path") == "example.org"

    def test_accepts_a_bare_host(self):
        assert host_of("example.org/path") == "example.org"

    def test_empty_is_empty(self):
        assert host_of(None) == ""
        assert host_of("") == ""


class TestAggregators:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.wemakescholars.com/bachelors-scholarships",
            "https://blog.wemakescholars.com/post",
            "https://scholarshipbob.com/scholarships-by-organisation/unesco",
            "https://www.opportunitiesforyouth.org/2026/01/fully-funded-scholarship/",
            "https://www.prospects.ac.uk/postgraduate-recruiters",
            "https://www.topuniversities.com/scholarships",
            "https://globalscholarships.com/scholarship-search/masters/japan/full-funding/",
            "https://www.scholarshipsads.com/search/country/japan-scholarships/",
            "https://www.globaladmissions.com/scholarships/japan/master",
        ],
    )
    def test_aggregator_hosts_are_recognised(self, url):
        assert is_aggregator_host(url)

    def test_the_matched_domain_is_reported(self):
        assert aggregator_host("https://www.wemakescholars.com/x") == "wemakescholars.com"

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.studyinjapan.go.jp/en/",
            "https://www.jasso.go.jp/en/ryugaku/scholarship_j/index.html",
            "https://www.daad.de/en/studying-in-germany/scholarships/",
            "https://www.chevening.org/scholarships/",
            "https://nus.edu.sg/oam/scholarships",
        ],
    )
    def test_official_providers_are_not_aggregators(self, url):
        assert not is_aggregator_host(url)

    def test_empty_is_not_an_aggregator(self):
        assert not is_aggregator_host("")
        assert not is_aggregator_host(None)


class TestSocialPlatformsAreBlockedToo:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=x",
            "https://youtu.be/x",
            "https://www.facebook.com/scholarship",
            "https://www.instagram.com/p/x",
            "https://wa.me/123",
            "https://t.me/scholarship",
        ],
    )
    def test_social_hosts_are_not_sources(self, url):
        assert is_blocked_source_host(url)
        assert blocked_source_host(url)

    def test_an_aggregator_is_also_blocked(self):
        assert is_blocked_source_host("https://www.wemakescholars.com/x")

    def test_an_official_host_is_not_blocked(self):
        assert not is_blocked_source_host("https://www.studyinjapan.go.jp/en/")
        assert not is_blocked_source_host("https://nus.edu.sg/oam/scholarships")
