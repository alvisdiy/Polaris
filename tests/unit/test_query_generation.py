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
