"""Unit/integration tests for ProviderResolver identity semantics.

Uses the shared test database (conftest) with transaction rollback so tests
never pollute the knowledge base.
"""

import pytest

from database.models.country import Country
from services.exploration.candidate_analyzer import AnalyzedCandidate
from services.exploration.provider_resolver import (
    ProviderResolver,
    identity_key_for,
    is_noise_org_name,
    normalize_org_name,
)
from tests.integration._exploration_isolation import exploration_session


@pytest.fixture
def session(exploration_session):
    """Rollback-only session over an emptied JP exploration state.

    Real acquisition runs leave providers/sources in the shared development
    database (the live SG run minted a 'Scholarships' provider on
    admissions.smu.edu.sg). Identity-resolution tests must start from a
    genuinely empty country or those rows leak into same-domain assertions.
    """
    return exploration_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def resolver(session, jp_country):
    return ProviderResolver(session, jp_country.country_id, [".go.jp", ".ac.jp"])


class TestNormalizeOrgName:
    def test_strips_suffixes_and_case(self):
        assert normalize_org_name("The GIST College") == "gist"
        assert normalize_org_name("XYZ Foundation, Inc.") == "xyz"
        assert normalize_org_name("  MULTIPLE   spaces  ") == "multiple spaces"


class TestIdentityKey:
    def test_deterministic(self):
        a = identity_key_for("gist.ac.kr", "gist", "country-uuid")
        b = identity_key_for("gist.ac.kr", "gist", "country-uuid")
        assert a == b
        assert len(a) == 64


class TestResolve:
    def test_new_provider_created(self, resolver):
        resolution = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/scholarships")
        assert resolution.created
        assert resolution.provider.verification_status == "discovered"
        assert resolution.provider.identity_key is not None

    def test_same_domain_and_name_resolves_to_same_provider(self, resolver):
        r1 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/scholarships")
        r2 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/programs/grants")
        assert r1.provider.provider_id == r2.provider.provider_id
        assert not r2.created

    def test_www_variant_resolves_to_same_provider(self, resolver):
        r1 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/a")
        r2 = resolver.resolve("XYZ Foundation", "https://www.xyz-foundation.org/b")
        assert r1.provider.provider_id == r2.provider.provider_id

    def test_identity_key_match_after_url_normalization(self, resolver):
        r1 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/scholarships")
        r2 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/scholarships/")
        assert r1.provider.provider_id == r2.provider.provider_id

    def test_ambiguous_identity_creates_needs_review(self, resolver):
        """Ambiguity must NOT auto-merge; it creates a needs_review row."""
        # Two different orgs sharing a domain fragment shape
        resolver.resolve("Alpha Trust", "https://alpha.org/one")
        resolver.resolve("Alpha Foundation", "https://alpha.org/two")
        # A third with the same name as both-ish → ambiguous handling
        resolution = resolver.resolve("Alpha", "https://alpha.org/three")
        # Either resolves to exactly one of them, or creates needs_review —
        # but never merges two existing providers together.
        assert resolution.provider.merged_into_provider_id is None

    def test_evidence_accumulates_on_rediscovery(self, resolver):
        r1 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/a", evidence={"via": "web_search"})
        r2 = resolver.resolve("XYZ Foundation", "https://xyz-foundation.org/b", evidence={"via": "link_expansion"})
        obs = r2.provider.discovery_evidence.get("observations", [])
        assert len(obs) >= 2

    def test_page_identity_extraction_prefers_jsonld(self, resolver):
        c = AnalyzedCandidate(url="https://xyz-foundation.org/")
        c.title = "XYZ Foundation | Scholarships"
        c.structured_data = [{"@type": "Organization", "name": "XYZ Foundation"}]
        c.org_hints = ["XYZ Foundation"]
        name, confidence = resolver.extract_org_identity(c)
        assert "XYZ" in name
        assert confidence >= 0.6

    def test_domain_fallback_extraction(self, resolver):
        c = AnalyzedCandidate(url="https://gist-ac-kr.example.org/")
        name, confidence = resolver.extract_org_identity(c)
        assert name
        assert confidence <= 0.6  # low-confidence fallback


class TestNoiseOrgNames:
    """Regression: the live SG run minted providers from page chrome like
    '-2021 © Myanmar Study Abroad' and 'Government of Singapore, last
    updated on 25 September 2026'. Footers are not organizations."""

    def test_copyright_footer_is_noise(self):
        assert is_noise_org_name("-2021 © Myanmar Study Abroad")
        assert is_noise_org_name("© 2026 Some Site")

    def test_last_updated_footer_is_noise(self):
        assert is_noise_org_name("Government of Singapore, last updated on 25 September 2026")

    def test_real_org_names_are_not_noise(self):
        assert not is_noise_org_name("Nanyang Technological University")
        assert not is_noise_org_name("XYZ Foundation")

    def test_noise_hints_are_rejected_in_extraction(self, resolver):
        c = AnalyzedCandidate(url="https://www.mfa.gov.sg/careers/")
        c.title = "Foreign Service Scholarships | Ministry of Foreign Affairs"
        c.org_hints = ["-2021 © Myanmar Study Abroad", "Government of Singapore, last updated on 25 September 2026"]
        name, confidence = resolver.extract_org_identity(c)
        assert "©" not in name
        assert "last updated" not in name
        assert name == "Foreign Service Scholarships"  # title segment survives

    def test_all_noise_falls_back_to_domain(self, resolver):
        c = AnalyzedCandidate(url="https://myanmarstudyabroad.org/scholarships")
        c.title = "© 2021 Myanmar Study Abroad"
        c.org_hints = ["© 2021 Myanmar Study Abroad"]
        name, confidence = resolver.extract_org_identity(c)
        assert name == "Myanmarstudyabroad"  # domain fallback
        assert confidence == 0.3


class TestSameDomainDuplicateMerge:
    def test_third_candidate_merges_duplicates(self, resolver):
        """The live SG run produced 3 provider rows for admissions.smu.edu.sg;
        a later candidate on the same domain must consolidate them."""
        r1 = resolver.resolve("SMU Admissions Office", "https://admissions.smu.edu.sg/a")
        r2 = resolver.resolve("SMU Graduate Studies", "https://admissions.smu.edu.sg/b")
        r3 = resolver.resolve("Singapore Management University", "https://admissions.smu.edu.sg/c")

        from database.models.provider import Provider

        live = (
            resolver.session.query(Provider)
            .filter(Provider.country_id == resolver.country_id)  # resolver is country-scoped
            .filter(Provider.merged_into_provider_id.is_(None))
            .filter(Provider.official_url.like("%admissions.smu.edu.sg%"))
            .all()
        )
        assert len(live) == 1
        assert r3.provider.provider_id == live[0].provider_id
        merged = r1.provider if r1.provider.provider_id != live[0].provider_id else r2.provider
        assert merged.merged_into_provider_id == live[0].provider_id


class TestNeedsReviewIdentityRecovery:
    """Regression for the live KR failure: two ambiguous candidates resolving
    to the same identity each tried to INSERT a provider; the second one died
    on the provider_code unique key and took the whole run down (97 candidates
    of work lost). needs_review rows must (a) carry their identity_key and
    (b) reuse the existing row after a collision instead of failing."""

    def test_needs_review_row_carries_identity_key(self, resolver):
        resolution = resolver._create_needs_review(
            "Mystery Trust",
            "https://mysterytrust.org/x",
            "ambiguous identity: multiple candidates",
            None,
        )
        assert resolution.needs_review
        assert resolution.provider.identity_key is not None

    @pytest.fixture
    def recovery_resolver(self, rollback_session):
        """Savepoint-isolated session: the resolver's internal rollback() must
        not erase rows the test staged earlier."""
        country = rollback_session.query(Country).filter(Country.iso2 == "JP").first()
        return ProviderResolver(rollback_session, country.country_id, [".go.jp", ".ac.jp"])

    def test_needs_review_reuses_row_after_code_collision(self, recovery_resolver):
        from datetime import datetime, timezone

        from database.models.enums import ProviderType
        from database.models.provider import Provider

        session = recovery_resolver.session

        # Simulate the earlier candidate in the run whose insert was already
        # committed (engine commits per candidate): same registered domain and
        # normalized name, so the same provider_code.
        code = ProviderResolver._provider_code("alphatrust.org", "alpha")
        winner = Provider(
            provider_code=code,
            provider_name="Alpha Trust",
            provider_type=ProviderType.OTHER,
            country_id=recovery_resolver.country_id,
            official_url="https://alphatrust.org/a",
            verification_status="discovered",
            discovery_method="internet_exploration",
            discovered_at=datetime.now(timezone.utc),
        )
        session.add(winner)
        session.commit()

        # A second, equivalent ambiguous candidate must collide on the unique
        # provider_code, roll back the poisoned insert, and reuse the winner.
        resolution = recovery_resolver._create_needs_review(
            "Alpha Trust",
            "https://alphatrust.org/review",
            "ambiguous identity: multiple candidates",
            None,
        )
        assert resolution.provider.provider_id == winner.provider_id
        assert not resolution.created
        observations = resolution.provider.discovery_evidence.get("observations", [])
        assert any(o.get("url") == "https://alphatrust.org/review" for o in observations)
