"""Discovery query generation.

Generates a bounded, prioritized query plan from the country configuration.
Templates are fixed in code (four families — no DSL); the vocabulary comes
from the country's terminology packs. Provider names are NEVER part of query
generation — MEXT/JASSO/DAAD/etc. may only emerge as search results.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from services.exploration.config_loader import CountryExplorationConfig

# Fixed family templates. Placeholders substitute from terminology packs.
# No provider names, no user-defined DSL.
FAMILY_TEMPLATES: dict[str, list[str]] = {
    "opportunity": [
        "{scholarship} in {country} for international students",
        "{funding} {scholarship} {country} {education}",
        "{education} {scholarship} {country}",
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
    ],
}

# Candidate-type hint per family (advisory; classifier decides later).
FAMILY_TYPE_HINT = {
    "opportunity": "opportunity",
    "provider": "provider",
    "official_source": "source",
    "localized": "opportunity",
}


@dataclass(frozen=True)
class PlannedQuery:
    text: str
    family: str
    candidate_type_hint: str


class QueryGenerator:
    """Deterministic, config-driven query plan generation."""

    def __init__(self, config: CountryExplorationConfig, seed: int | None = None) -> None:
        self.config = config
        self._rng = random.Random(seed)

    def _latin(self, pack: str) -> str:
        """Pick an ASCII term from a terminology pack (single-script queries)."""
        terms = [t for t in self.config.terminology.get(pack, []) if t.isascii()]
        return self._rng.choice(terms) if terms else ""

    def _native(self, pack: str) -> str:
        """Pick a non-Latin (native-script) term, falling back to any term."""
        terms = self.config.terminology.get(pack, [])
        non_latin = [t for t in terms if not t.isascii()]
        return self._rng.choice(non_latin or terms) if terms else ""

    def _render_latin(self, template: str) -> str:
        return (
            template.replace("{scholarship}", self._latin("scholarship"))
            .replace("{education}", self._latin("education"))
            .replace("{provider}", self._latin("provider"))
            .replace("{funding}", self._latin("funding"))
            .replace("{country}", self.config.country_name)
            .replace("{country_local}", self.config.country_local or self.config.country_name)
        )

    def _render_native(self, template: str) -> str:
        """Render a localized query fully in the country's native script."""
        country = self.config.country_local or self.config.country_name
        return (
            template.replace("{scholarship}", self._native("scholarship"))
            .replace("{education}", self._native("education"))
            .replace("{provider}", self._native("provider"))
            .replace("{funding}", self._native("funding"))
            .replace("{country}", country)
            .replace("{country_local}", country)
        )

    def generate_plan(self, run_offset: int = 0) -> list[PlannedQuery]:
        """Build the bounded query plan for one run.

        Families are visited round-robin; each visit renders the family's
        next template with fresh terminology. `run_offset` rotates the start
        so successive runs explore different query combinations.
        """
        families = [f for f in self.config.query_families if f in FAMILY_TEMPLATES]
        if not families:
            return []

        plan: list[PlannedQuery] = []
        seen: set[str] = set()
        budget = self.config.max_queries_per_run

        cursor = run_offset % len(families)
        cycles = 0
        while len(plan) < budget and cycles < len(families) * 4:
            family = families[cursor % len(families)]
            templates = FAMILY_TEMPLATES[family]
            template = templates[(run_offset + cycles) % len(templates)]

            # Latin families: English/international queries. Localized family:
            # native-script queries in the country's own language.
            if family == "localized":
                text = self._render_native(template)
            else:
                text = self._render_latin(template)
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

        return plan[:budget]
