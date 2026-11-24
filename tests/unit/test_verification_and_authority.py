"""Unit tests for VerificationEngine (strict) and AuthoritySourceResolver."""

import pytest

from services.exploration.authority_source_resolver import (
    AUTHORITY_CANDIDATES_FOUND,
    AUTHORITY_RESOLVED,
    AUTHORITY_UNRESOLVED,
    AuthoritySourceResolver,
)
from services.exploration.engine import org_identity_matches
from services.exploration.search.base import SearchResult
from services.exploration.verification_engine import (
    STATE_DISCOVERED,
    STATE_NEEDS_REVIEW,
    STATE_VERIFIED,
    VerificationEngine,
)


class TestVerificationEngine:
    @pytest.fixture
    def verifier(self):
        return VerificationEngine(
            soft_domain_signals=[".go.jp", ".ac.jp"],
            auto_verify_threshold=0.75,
            review_threshold=0.45,
        )

    def test_strong_official_page_verifies(self, verifier):
        verdict = verifier.verify_source(
            "https://www.jasso.go.jp/scholarships/index.html",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="JASSO",
            scholarship_content=True,
        )
        assert verdict.state == STATE_VERIFIED
        assert verdict.confidence >= 0.75

    def test_tld_alone_never_verifies(self, verifier):
        """CRITICAL: .ac.jp alone must NOT auto-verify."""
        verdict = verifier.verify_source(
            "https://random-university.ac.jp/some/page",
            https_ok=True,
            reachable=True,
            org_identity_match=False,
            provider_name="Unknown",
            scholarship_content=False,
        )
        assert verdict.state != STATE_VERIFIED

    def test_keyword_alone_never_verifies(self, verifier):
        verdict = verifier.verify_source(
            "https://random-blog.com/scholarship-list",
            https_ok=True,
            reachable=True,
            org_identity_match=False,
            provider_name="Unknown",
            scholarship_content=True,
        )
        assert verdict.state in (STATE_NEEDS_REVIEW, STATE_DISCOVERED)

    def test_nothing_at_all_is_discovered(self, verifier):
        verdict = verifier.verify_source("http://random-site.com/")
        assert verdict.state == STATE_DISCOVERED
        assert verdict.confidence == 0.0

    def test_medium_confidence_needs_review(self, verifier):
        verdict = verifier.verify_source(
            "https://some-foundation.org/scholarship",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="Some Foundation",
            scholarship_content=False,
        )
        assert verdict.state == STATE_NEEDS_REVIEW

    def test_auto_verify_disabled_stays_review(self):
        strict = VerificationEngine(
            soft_domain_signals=[".ac.jp"],
            auto_verify_threshold=0.75,
            review_threshold=0.45,
            auto_verify_enabled=False,
        )
        verdict = strict.verify_source(
            "https://www.jasso.go.jp/scholarships",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="JASSO",
            scholarship_content=True,
        )
        assert verdict.state == STATE_NEEDS_REVIEW

    def test_official_host_still_verifies_after_aggregator_guard(self):
        """The aggregator guard must not break genuine .go.jp verification."""
        verdict = self._verifier().verify_source(
            "https://www.jasso.go.jp/scholarships/index.html",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="JASSO",
            scholarship_content=True,
        )
        assert verdict.state == STATE_VERIFIED
        assert verdict.signals["official_host"] is True

    def test_sg_official_host_still_verifies(self):
        verdict = self._verifier().verify_source(
            "https://www.psc.gov.sg/scholarships",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="Public Service Commission",
            scholarship_content=True,
        )
        assert verdict.state == STATE_VERIFIED

    def test_aggregator_never_auto_verifies(self):
        """Regression: finaid.org reached VERIFIED in the live SG run on
        content score alone; aggregator domains must cap at NEEDS_REVIEW."""
        verdict = self._verifier().verify_source(
            "https://finaid.org/scholarships/",
            https_ok=True,
            reachable=True,
            org_identity_match=True,
            provider_name="Finaid",
            scholarship_content=True,
            structured_data=True,
        )
        assert verdict.state == STATE_NEEDS_REVIEW
        assert "aggregator guard" in verdict.reasoning

    @staticmethod
    def _verifier():
        return VerificationEngine(
            soft_domain_signals=[".go.jp", ".ac.jp", ".gov.sg", ".edu.sg"],
            auto_verify_threshold=0.75,
            review_threshold=0.45,
        )


class TestOrgIdentityMatches:
    """The authority resolver stores the registered domain; candidates
    arrive with full hosts. The comparison must be registered-to-registered
    or no subdomain source can ever earn the org-identity signal."""

    def test_subdomain_of_provider_domain_matches(self):
        assert org_identity_matches(
            "uni.ac.jp", "https://scholarships.uni.ac.jp/apply"
        )

    def test_apex_and_www_hosts_match(self):
        assert org_identity_matches("jasso.go.jp", "https://www.jasso.go.jp/x")
        assert org_identity_matches("jasso.go.jp", "https://jasso.go.jp/x")

    def test_other_institution_does_not_match(self):
        assert not org_identity_matches(
            "uni.ac.jp", "https://other.ac.jp/scholarships"
        )

    def test_lookalike_domain_does_not_match(self):
        assert not org_identity_matches(
            "uni.ac.jp", "https://uni.ac.jp.evil.example/phish"
        )

    def test_missing_inputs_never_match(self):
        assert not org_identity_matches(None, "https://uni.ac.jp/x")
        assert not org_identity_matches("", "https://uni.ac.jp/x")
        assert not org_identity_matches("uni.ac.jp", "not a url")


class _FakeSearchProvider:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.queries = []

    async def search(self, query):
        self.queries.append(query.text)
        return self.results_by_query.get(query.text, [])


class TestAuthoritySourceResolver:
    @pytest.fixture
    def resolver(self):
        return AuthoritySourceResolver(
            search_provider=None,  # replaced per-test
            soft_domain_signals=[".ac.kr", ".go.kr"],
        )

    @pytest.fixture
    def provider(self):
        return _FakeSearchProvider(
            {
                '"GIST" official site': [
                    SearchResult(url="https://www.gist.ac.kr/", title="Gwangju Institute of Science and Technology", position=1),
                    SearchResult(url="https://aggregator.example.net/gist-info", title="GIST info", position=2),
                ],
                '"GIST" scholarship': [
                    SearchResult(url="https://www.gist.ac.kr/admission/scholarship.html", title="GIST Scholarship", position=1),
                    SearchResult(url="https://blog.example.com/gist-scholarship-review", title="GIST scholarship review", position=2),
                ],
            }
        )

    @pytest.mark.asyncio
    async def test_official_domain_wins_over_aggregator(self, resolver, provider):
        resolver.search_provider = provider
        result = await resolver.resolve("GIST", provider_domain="gist.ac.kr")
        assert result.status in (AUTHORITY_RESOLVED, AUTHORITY_CANDIDATES_FOUND)
        assert "gist.ac.kr" in result.official_page.url
        # aggregator/blog must NOT be the top candidate
        assert "aggregator" not in result.official_page.url
        assert "blog" not in result.official_page.url

    @pytest.mark.asyncio
    async def test_discovery_page_not_treated_as_authority(self, resolver, provider):
        resolver.search_provider = provider
        result = await resolver.resolve("GIST", provider_domain="gist.ac.kr")
        # The resolution must reference the official domain, not the blog/aggregator
        assert result.provider_domain == "gist.ac.kr"

    @pytest.mark.asyncio
    async def test_no_results_is_unresolved_not_error(self, resolver):
        resolver.search_provider = _FakeSearchProvider({})
        result = await resolver.resolve("Unknown Org", provider_domain=None)
        assert result.status == AUTHORITY_UNRESOLVED

    @pytest.mark.asyncio
    async def test_search_failure_is_tolerated(self, resolver):
        class FailingProvider:
            async def search(self, query):
                raise RuntimeError("provider down")

        resolver.search_provider = FailingProvider()
        result = await resolver.resolve("GIST", provider_domain=None)
        assert result.status == AUTHORITY_UNRESOLVED
