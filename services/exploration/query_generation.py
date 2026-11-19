"""Discovery query generation.

Generates a bounded, prioritized query plan from the country configuration.
Templates are fixed in code — no DSL. The vocabulary comes from the country's
terminology packs. Provider names are NEVER part of query generation —
MEXT/JASSO/DAAD/etc. may only emerge as search results.

Three properties this module is responsible for:

**Deterministic.** The same (country, offset) always produces the same plan.
The previous version seeded ``random.Random(None)`` — OS entropy — and the
engine passed a wall-clock-derived offset, so two runs of the same country
produced different queries and nothing about a run could be reproduced. Seed is
now derived from the ISO2 code, and the offset is an explicit argument.

**Bounded.** Families are templates, not a Cartesian product. Cross-multiplying
scholarship x funding x degree x provider x surface would generate hundreds of
near-identical queries and burn the per-run budget on one phrasing.

**Funding as a signal, never a requirement.** A funding term widens the net;
it never narrows it. ``fully funded scholarship <country>`` is worth running
because it finds pages that describe coverage, not because a scholarship must
say "fully funded" to be found. Funding classification happens at extraction,
where evidence exists.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from services.exploration.config_loader import CountryExplorationConfig

# Fixed family templates. Placeholders substitute from terminology packs.
# No provider names, no user-defined DSL.
#
# Four families carried the whole engine before. They are kept intact — they
# are the only ones with proven yield — and three more are added below to
# reach the scholarship shapes the engine was not asking for at all.
FAMILY_TEMPLATES: dict[str, list[str]] = {
    "opportunity": [
        "{scholarship} in {country} for international students",
        "{funding} {scholarship} {country} {education}",
        "{education} {scholarship} {country}",
    ],
    # Official-domain search. A generic "scholarship in Japan" returns
    # aggregators and listicles; `site:ac.jp` returns the universities' own
    # scholarship pages. The operator is supported by the search backend
    # (measured on DDGS: `site:ac.jp` and `site:go.jp` both return official
    # results), and it is the cheapest way to make discovery source-first.
    "official_domain": [
        "{scholarship} site:{tld}",
        "{country} {scholarship} site:{tld}",
    ],
    "provider": [
        "{country} {provider} {scholarship}",
        "{country} government {scholarship}",
    ],
    "official_source": [
        "{country} {scholarship} official site",
        "{country} university {scholarship} application",
    ],
    "localized": [
        "{country_local} {scholarship} {education}",
        "{country_local} {scholarship} {funding}",
        "{country_local} {education} {scholarship}",
    ],
    # Funding breadth. These name a *kind* of coverage, so they surface
    # awards the generic templates miss — a page saying "tuition fee
    # scholarship" never contains "fully funded" and was never queried for.
    # Pairs with the degree/education pack already in every config.
    "funding": [
        "{funding} {scholarship} {country}",
        "{funding} {scholarship} {country} {education}",
    ],
    # Degree level. The `opportunity` family buries the level inside a long
    # phrase; these ask for it directly, which is how a PhD-only listing is
    # found at all.
    "degree": [
        "{education} {scholarship} {country}",
        "{country} {education} {scholarship} programme",
    ],
    # Provider ecosystem. Named because a scholarship index usually lives on a
    # ministry/foundation/university *site*, not inside a generic result.
    "ecosystem": [
        "ministry of education {scholarship} {country}",
        "national {scholarship} {country} official",
        "{country} {provider} {scholarship} programme",
    ],
}

# Candidate-type hint per family (advisory; classifier decides later).
FAMILY_TYPE_HINT = {
    "opportunity": "opportunity",
    "official_domain": "opportunity",
    "provider": "provider",
    "official_source": "source",
    "localized": "opportunity",
    "funding": "opportunity",
    "degree": "opportunity",
    "ecosystem": "source",
}

#: Families rendered in the country's native script. Everything else is Latin.
_NATIVE_FAMILIES = frozenset({"localized"})


@dataclass(frozen=True)
class PlannedQuery:
    text: str
    family: str
    candidate_type_hint: str


def _stable_seed(value: str) -> int:
    """A process-stable integer seed derived from ``value``."""
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


class QueryGenerator:
    """Deterministic, config-driven query plan generation."""

    def __init__(self, config: CountryExplorationConfig, seed: int | None = None) -> None:
        self.config = config
        # Seeded from the country so a run is reproducible. `seed` stays a
        # parameter for tests that want two deliberately different plans.
        #
        # `hash()` is NOT usable here: CPython randomizes str hashing per
        # process (PYTHONHASHSEED), so a seed derived from it changes between
        # interpreter runs and the plan is only reproducible *within* one
        # process — which looks correct in a test and is not correct in
        # production. sha256 is stable across processes and machines.
        self._rng = random.Random(
            seed if seed is not None else _stable_seed(config.iso2)
        )
        # Rotated, not randomly chosen: a country with four official TLDs must
        # eventually query all of them. Random choice gave two `.or.jp` queries
        # in a row and never touched `.ac.jp` in that run.
        self._tld_cursor = 0

    def _latin(self, pack: str) -> str:
        """Pick an ASCII term from a terminology pack (single-script queries)."""
        terms = [t for t in self.config.terminology.get(pack, []) if t.isascii()]
        return self._rng.choice(terms) if terms else ""

    def _next_tld(self) -> str:
        """The next official TLD for this country, without the leading dot.

        Config values are written as suffixes (\".ac.jp\") because that is how
        the verifier reads them; the search operator wants ``ac.jp``. Rotation
        order is the config order, which is ordered most-authoritative first
        (``.go.jp`` before ``.or.jp``).
        """
        tlds = [
            signal.strip().lstrip(".")
            for signal in self.config.soft_domain_signals
            if signal.strip()
        ]
        if not tlds:
            return ""
        value = tlds[self._tld_cursor % len(tlds)]
        self._tld_cursor += 1
        return value

    def _native(self, pack: str) -> str:
        """Pick a non-Latin (native-script) term, falling back to any term."""
        terms = self.config.terminology.get(pack, [])
        non_latin = [t for t in terms if not t.isascii()]
        return self._rng.choice(non_latin or terms) if terms else ""

    def _render_latin(self, template: str) -> str:
        tld = self._next_tld() if "{tld}" in template else ""
        return (
            template.replace("{scholarship}", self._latin("scholarship"))
            .replace("{education}", self._latin("education"))
            .replace("{provider}", self._latin("provider"))
            .replace("{funding}", self._latin("funding"))
            .replace("{country}", self.config.country_name)
            .replace("{country_local}", self.config.country_local or self.config.country_name)
            .replace("{tld}", tld)
        )

    def _render_native(self, template: str) -> str:
        """Render a localized query fully in the country's native script."""
        country = self.config.country_local or self.config.country_name
        tld = self._next_tld() if "{tld}" in template else ""
        return (
            template.replace("{scholarship}", self._native("scholarship"))
            .replace("{education}", self._native("education"))
            .replace("{provider}", self._native("provider"))
            .replace("{funding}", self._native("funding"))
            .replace("{country}", country)
            .replace("{country_local}", country)
            .replace("{tld}", tld)
        )

    def generate_plan(self, run_offset: int = 0) -> list[PlannedQuery]:
        """Build the bounded query plan for one run.

        Families are visited round-robin; each visit renders the family's
        next template with fresh terminology. `run_offset` rotates the start
        so successive runs explore different query combinations.

        Determinism note: the rotation is driven entirely by ``run_offset`` and
        the country-seeded RNG. Two calls with the same arguments produce the
        same plan, which is what makes a run reproducible after a failure.
        """
        families = [
            f
            for f in self.config.query_families
            if f in FAMILY_TEMPLATES
            and not (f == "official_domain" and not self.config.soft_domain_signals)
        ]
        if not families:
            return []

        # Start the TLD rotation at the run offset so successive runs cover
        # different official domains without becoming non-deterministic.
        self._tld_cursor = run_offset

        plan: list[PlannedQuery] = []
        seen: set[str] = set()
        budget = self.config.max_queries_per_run

        cursor = run_offset % len(families)
        cycles = 0
        while len(plan) < budget and cycles < len(families) * 4:
            family = families[cursor % len(families)]
            templates = FAMILY_TEMPLATES[family]
            template = templates[(run_offset + cycles) % len(templates)]

            text = (
                self._render_native(template)
                if family in _NATIVE_FAMILIES
                else self._render_latin(template)
            )
            text = " ".join(text.split())

            if text and text not in seen:
                seen.add(text)
                plan.append(
                    PlannedQuery(
                        text=text,
                        family=family,
                        candidate_type_hint=FAMILY_TYPE_HINT.get(family, "unknown"),
                    )
                )
            cursor += 1
            if cursor % len(families) == 0:
                cycles += 1

        # The previous round-robin could leave a run with only one localized
        # query (or none at some offsets). Reserve a second localized slot for
        # countries with a configured non-English language without increasing
        # the provider query budget.
        if (
            "localized" in families
            and any(language.casefold() != "en" for language in self.config.languages)
        ):
            localized_count = sum(query.family == "localized" for query in plan)
            replacement_indexes = [
                index for index in range(len(plan) - 1, -1, -1)
                if plan[index].family != "localized"
            ]
            template_index = 0
            while localized_count < 2 and replacement_indexes:
                template = FAMILY_TEMPLATES["localized"][
                    template_index % len(FAMILY_TEMPLATES["localized"])
                ]
                template_index += 1
                text = " ".join(self._render_native(template).split())
                if not text or text in seen:
                    continue
                seen.add(text)
                index = replacement_indexes.pop(0)
                plan[index] = PlannedQuery(
                    text=text,
                    family="localized",
                    candidate_type_hint=FAMILY_TYPE_HINT["localized"],
                )
                localized_count += 1

        return plan[:budget]
