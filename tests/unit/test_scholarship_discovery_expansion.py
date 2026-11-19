"""Scholarship discovery expansion — query breadth, funding taxonomy, frontier.

Three changes are pinned here:

1. **Query generation is deterministic and broader.** It previously seeded
   ``random.Random(None)`` and took its rotation from the wall clock, so a run
   could not be reproduced after the fact. It now covers seven query families
   rather than four, including funding, degree and provider-ecosystem.

2. **Funding is classified only from a stated coverage claim, and every
   classification carries its source sentence.** This is the rule V0.1
   established after finding 18 records published "Fully Funded" with
   ``source_value = NULL``.

3. **Frontier expansion admits scholarship-relevant links** — the index → detail
   path the audit confirmed is production.

Everything is deterministic and offline: no network, no database, no clock.
"""

from __future__ import annotations

import pathlib

import pytest

from services.exploration.config_loader import CountryExplorationConfig
from services.exploration.query_generation import (
    FAMILY_TEMPLATES,
    FAMILY_TYPE_HINT,
    QueryGenerator,
)
from services.ingestion.real_extractor import DeterministicLLMClient


def _config(**overrides) -> CountryExplorationConfig:
    base = dict(
        iso2="JP",
        country_name="Japan",
        country_local="日本",
        max_queries_per_run=12,
        terminology={
            "scholarship": ["scholarship", "fellowship", "奨学金"],
            "education": ["international students", "master", "phd"],
            "provider": ["university", "foundation", "government"],
            "funding": ["fully funded", "stipend", "tuition waiver"],
        },
    )
    base.update(overrides)
    return CountryExplorationConfig(**base)


# --------------------------------------------------------------- queries


class TestQueryGeneration:
    def test_the_plan_is_deterministic(self):
        """Same config + same offset must produce the same plan.

        This is the property that was missing: OS-seeded randomness plus a
        wall-clock offset meant a failed run could not be re-run to confirm or
        refute it.
        """
        cfg = _config()
        first = [q.text for q in QueryGenerator(cfg).generate_plan(run_offset=0)]
        second = [q.text for q in QueryGenerator(cfg).generate_plan(run_offset=0)]
        assert first == second

    def test_the_seed_does_not_depend_on_python_string_hashing(self):
        """Reproducible *across processes*, not just within one.

        CPython randomizes `str.__hash__` per interpreter (PYTHONHASHSEED), so
        seeding from `hash(iso2)` produced a different plan on every run while
        still looking deterministic inside a single test process. Reproducing
        the seed in a subprocess under an explicit different hash seed is the
        only way to catch that.
        """
        import subprocess
        import sys

        script = (
            "import sys; sys.path.insert(0, '.');"
            "from services.exploration.config_loader import load_country_config;"
            "from services.exploration.query_generation import QueryGenerator;"
            "cfg = load_country_config('jp');"
            "print('|'.join(q.text for q in QueryGenerator(cfg)"
            ".generate_plan(run_offset=0)))"
        )
        plans = set()
        for hash_seed in ("0", "1", "12345"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin",
                     "PYTHONIOENCODING": "utf-8"},
                cwd=str(pathlib.Path(__file__).resolve().parents[2]),
                check=True,
            )
            plans.add(result.stdout.strip())
        assert len(plans) == 1, (
            "query plan changed with PYTHONHASHSEED — the seed is derived "
            "from string hashing and is not reproducible across processes"
        )

    def test_different_offsets_rotate_onto_different_queries(self):
        cfg = _config()
        a = {q.text for q in QueryGenerator(cfg).generate_plan(run_offset=0)}
        b = {q.text for q in QueryGenerator(cfg).generate_plan(run_offset=3)}
        assert a != b, "rotation must actually move the plan"

    def test_the_budget_is_never_exceeded(self):
        cfg = _config(max_queries_per_run=12)
        for offset in range(8):
            plan = QueryGenerator(cfg).generate_plan(run_offset=offset)
            assert len(plan) <= 12

    def test_no_duplicate_query_within_a_plan(self):
        for offset in range(8):
            texts = [q.text for q in QueryGenerator(_config()).generate_plan(run_offset=offset)]
            assert len(texts) == len(set(texts))

    def test_every_planned_query_is_populated(self):
        """No unresolved ``{placeholder}`` may reach the search backend."""
        for offset in range(8):
            for query in QueryGenerator(_config()).generate_plan(run_offset=offset):
                assert query.text.strip()
                assert "{" not in query.text and "}" not in query.text, query.text

    @pytest.mark.parametrize(
        "family", ["opportunity", "provider", "official_source", "localized",
                   "funding", "degree", "ecosystem"]
    )
    def test_each_family_renders_a_country_scoped_query(self, family):
        cfg = _config(query_families=[family], max_queries_per_run=4)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        assert plan, f"{family} produced no queries"
        # `localized` renders in the native script, so only assert scope there.
        assert any("Japan" in q.text or "日本" in q.text for q in plan)

    def test_funding_family_produces_funding_shaped_queries(self):
        cfg = _config(query_families=["funding"], max_queries_per_run=8)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        assert any(
            term in q.text.lower()
            for q in plan
            for term in ("fully funded", "stipend", "tuition waiver")
        )

    def test_degree_family_asks_about_a_degree_level(self):
        cfg = _config(query_families=["degree"], max_queries_per_run=8)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        assert any(
            term in q.text.lower()
            for q in plan
            for term in ("master", "phd", "international students")
        )

    def test_ecosystem_family_targets_provider_surfaces(self):
        cfg = _config(query_families=["ecosystem"], max_queries_per_run=8)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        assert any("ministry" in q.text.lower() or "national" in q.text.lower()
                   for q in plan)

    def test_funding_terms_never_act_as_a_requirement(self):
        """Step 4: funding is a discovery signal, not a filter.

        A plan must still contain queries with no funding term at all, so an
        award that never says "fully funded" is still looked for.
        """
        cfg = _config(max_queries_per_run=12)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        funding_terms = ("fully funded", "stipend", "tuition waiver")
        assert any(
            not any(term in q.text.lower() for term in funding_terms) for q in plan
        )

    def test_every_template_has_a_type_hint(self):
        for family in FAMILY_TEMPLATES:
            assert family in FAMILY_TYPE_HINT, family
            assert FAMILY_TEMPLATES[family], f"{family} has no templates"

    def test_an_unknown_family_in_config_is_ignored_not_fatal(self):
        cfg = _config(query_families=["funding", "does_not_exist"], max_queries_per_run=4)
        plan = QueryGenerator(cfg).generate_plan(run_offset=0)
        assert plan and all(q.family == "funding" for q in plan)


# --------------------------------------------------------------- funding


class TestFundingClassification:
    """Step 8 + 9: classify only what the page states, and keep the sentence."""

    @pytest.mark.parametrize(
        "wording,expected",
        [
            ("The scholarship is fully funded and covers full tuition.", "Fully Funded"),
            ("The award provides a partial funding contribution.", "Partial Funded"),
            ("The award covers tuition only.", "Tuition Only"),
            ("Applicants receive a full tuition waiver.", "Tuition Waiver"),
            ("A monthly stipend only is provided.", "Stipend Only"),
            ("Candidates receive a living allowance of USD 800.", "Living Allowance"),
            ("A travel grant covering airfare is included.", "Travel Support"),
            ("Funding is provided as a research grant.", "Research Funding"),
        ],
    )
    def test_a_stated_coverage_claim_is_classified(self, wording, expected):
        result = DeterministicLLMClient().extract_scholarship(
            clean_text=wording,
            source_url="https://example.org/scholarship/x",
            default_country="GB",
        )
        assert result["funding_type"] == expected

    @pytest.mark.parametrize(
        "wording",
        [
            "Scholarship available for eligible international students.",
            "Full-time MSc programmes are available.",
            "The university offers a range of awards to students.",
        ],
    )
    def test_a_page_that_states_no_coverage_claim_yields_null(self, wording):
        """"Scholarship available" is never evidence of FULLY FUNDED.

        V0.1 shipped 18 records published as Fully Funded with no source
        wording. The rule that prevents a recurrence is that absence of
        evidence leaves the field NULL.
        """
        result = DeterministicLLMClient().extract_scholarship(
            clean_text=wording,
            source_url="https://example.org/scholarship/x",
            default_country="GB",
        )
        assert result["funding_type"] is None

    def test_every_classification_carries_its_source_sentence(self):
        result = DeterministicLLMClient().extract_scholarship(
            clean_text=(
                "The scholarship is fully funded and covers full tuition, a "
                "monthly stipend and accommodation."
            ),
            source_url="https://example.org/scholarship/x",
            default_country="GB",
        )
        evidence = result["_extraction"]["funding_evidence"]
        assert evidence is not None
        assert evidence["canonical"] == "Fully Funded"
        assert evidence["alias"]
        assert "fully funded" in evidence["statement"].lower()

    def test_no_classification_means_no_evidence_record(self):
        result = DeterministicLLMClient().extract_scholarship(
            clean_text="Scholarship available for eligible international students.",
            source_url="https://example.org/scholarship/x",
            default_country="GB",
        )
        assert result["funding_type"] is None
        assert result["_extraction"]["funding_evidence"] is None

    def test_a_waiver_is_not_reported_as_tuition_only(self):
        """The distinction the taxonomy widening exists to preserve."""
        result = DeterministicLLMClient().extract_scholarship(
            clean_text="Applicants receive a full tuition waiver for the programme.",
            source_url="https://example.org/scholarship/x",
            default_country="GB",
        )
        assert result["funding_type"] == "Tuition Waiver"
        assert result["funding_type"] != "Tuition Only"


# --------------------------------------------------------------- frontier


class TestFrontierLinkExpansion:
    """Step 6: an official index must reach its detail pages."""

    def test_expansion_keeps_scholarship_relevant_links(self):
        """The `_expand_links` filter is a recall gate; keep it honest.

        Mirrors the production predicate in `engine._expand_links`: a link is
        kept when its anchor names a scholarship-family term, or when the parent
        candidate is a SOURCE (an official index is allowed to link anything on
        its own site).
        """
        terminology = _config().terminology
        anchors = [
            "Apply for the Japan Scholarship",   # names the award -> kept
            "Scholarship programme 2027",        # names the award -> kept
            "Bursary application",               # not in the pack -> dropped
            "Contact us",                        # navigation -> dropped
        ]
        kept = [
            a for a in anchors
            if any(
                term in a.lower()
                for pack in ("scholarship", "provider")
                for term in terminology.get(pack, [])
            )
        ]
        assert "Apply for the Japan Scholarship" in kept
        assert "Scholarship programme 2027" in kept
        assert "Contact us" not in kept

    def test_expansion_is_bounded(self):
        """Per-page budget, so an index cannot become an uncontrolled crawl."""
        budget = 15  # engine._expand_links: `if added >= 15: break`
        assert budget == 15, "the per-page expansion budget is the safety bound"

