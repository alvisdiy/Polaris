"""Unit tests for QueryGenerator (config-driven, no provider names, bounded)."""

import pytest

from services.exploration.config_loader import load_country_config
from services.exploration.query_generation import FAMILY_TEMPLATES, PlannedQuery, QueryGenerator


@pytest.fixture
def jp_config():
    return load_country_config("jp")


@pytest.fixture
def cn_config():
    return load_country_config("cn")


PROVIDER_NAMES = ["mext", "jasso", "daad", "gist", "csc", "chevening", "lpdp"]


class TestPlanGeneration:
    def test_plan_respects_budget(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        assert len(plan) == jp_config.max_queries_per_run
        assert all(isinstance(q, PlannedQuery) for q in plan)

    def test_plan_covers_all_families(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        families = {q.family for q in plan}
        assert {"opportunity", "provider", "official_source", "localized"} <= families

    def test_plan_queries_unique(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        texts = [q.text for q in plan]
        assert len(texts) == len(set(texts))

    def test_no_provider_names_in_any_query(self, jp_config, cn_config):
        """CRITICAL: query generation must never encode provider names."""
        for config in (jp_config, cn_config):
            for seed in range(5):
                plan = QueryGenerator(config, seed=seed).generate_plan()
                for q in plan:
                    for provider in PROVIDER_NAMES:
                        assert provider not in q.text.lower()

    def test_no_provider_names_in_templates(self):
        for templates in FAMILY_TEMPLATES.values():
            for template in templates:
                for provider in PROVIDER_NAMES:
                    assert provider not in template.lower()

    def test_run_offset_rotates_plan(self, jp_config):
        gen = QueryGenerator(jp_config, seed=1)
        plan_a = gen.generate_plan(run_offset=0)
        plan_b = gen.generate_plan(run_offset=1)
        assert plan_a[0].text != plan_b[0].text

    def test_all_queries_nonempty(self, jp_config):
        plan = QueryGenerator(jp_config, seed=3).generate_plan()
        assert all(q.text.strip() for q in plan)


class TestLocalization:
    def test_localized_queries_use_native_script(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        localized = [q for q in plan if q.family == "localized"]
        assert localized
        for q in localized:
            assert any(not ch.isascii() for ch in q.text), f"not native: {q.text}"

    @pytest.mark.parametrize("iso2", ["JP", "KR", "CN", "SG", "ID", "DE", "FR"])
    def test_every_run_reserves_two_localized_queries(self, iso2):
        config = load_country_config(iso2)
        for offset in range(7):
            plan = QueryGenerator(config, seed=1).generate_plan(run_offset=offset)
            localized = [query for query in plan if query.family == "localized"]
            assert len(localized) >= 2
            if iso2 in {"JP", "KR", "CN", "SG"}:
                assert all(any(not char.isascii() for char in query.text) for query in localized)

    def test_latin_queries_stay_single_script(self, jp_config):
        """Non-localized queries must not mix scripts (search quality)."""
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        for q in plan:
            if q.family != "localized":
                assert all(ch.isascii() for ch in q.text), f"mixed script: {q.text}"

    def test_cn_localized_uses_chinese(self, cn_config):
        plan = QueryGenerator(cn_config, seed=2).generate_plan()
        localized = [q for q in plan if q.family == "localized"]
        assert localized
        assert any("奖学金" in q.text or "留学" in q.text for q in localized)


class TestOfficialDomainQueries:
    def test_jp_plan_uses_the_site_operator(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        official = [q for q in plan if q.family == "official_domain"]
        assert official, "official_domain family must appear in the plan"
        tlds = {s.lstrip(".") for s in jp_config.soft_domain_signals}
        for query in official:
            assert "site:" in query.text
            assert any(query.text.rstrip().endswith(tld) for tld in tlds), query.text

    def test_tlds_rotate_across_runs(self, jp_config):
        first = QueryGenerator(jp_config, seed=1).generate_plan(run_offset=0)
        second = QueryGenerator(jp_config, seed=1).generate_plan(run_offset=1)
        first_tlds = [q.text.rsplit("site:", 1)[-1] for q in first if q.family == "official_domain"]
        second_tlds = [q.text.rsplit("site:", 1)[-1] for q in second if q.family == "official_domain"]
        assert first_tlds != second_tlds, "successive runs must query different official TLDs"

    def test_family_is_absent_without_official_tlds(self, jp_config):
        config = jp_config.model_copy(
            update={"soft_domain_signals": [], "query_families": ["official_domain"]}
        )
        assert QueryGenerator(config, seed=1).generate_plan() == []

    @pytest.mark.parametrize("iso2", ["JP", "KR", "CN", "SG", "ID", "DE", "FR", "GB", "AU", "US"])
    def test_every_country_has_official_seed_portals(self, iso2):
        config = load_country_config(iso2)
        assert config.seed_urls, f"{iso2} has no seed_urls"
        assert all(url.startswith("https://") for url in config.seed_urls)


class TestTypeHints:
    def test_family_type_hints(self, jp_config):
        plan = QueryGenerator(jp_config, seed=1).generate_plan()
        for q in plan:
            if q.family == "opportunity":
                assert q.candidate_type_hint == "opportunity"
            elif q.family == "provider":
                assert q.candidate_type_hint == "provider"
            elif q.family == "official_source":
                assert q.candidate_type_hint == "source"
