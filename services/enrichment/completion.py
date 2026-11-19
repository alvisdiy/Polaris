"""Deterministic field completion for stored scholarships.

The pipeline does not need a model to notice that a record has no deadline. A
page was fetched, the document is still in ``raw_document``, and the extractors
that read it are deterministic. What was missing was a step that *re-reads* the
stored document and fills the fields the first pass left empty.

This module is that step. It never guesses:

* only fields that are currently empty are proposed;
* a value is proposed only when the extractor returns exactly one answer;
* a deadline is proposed only when the page does not contradict itself, and the
  date is plausible (this year or later, at most five years out);
* a multi-level award is proposed as a set only when the page lists the levels
  under a level label (``degree_levels.declared_award_levels``);
* every accepted proposal is written through ``ReviewService.correct`` with the
  actor recorded, so the change has a version, an audit row and evidence — the
  same trail a human edit leaves.

Nothing here calls an LLM. Running it twice is a no-op, which is what makes it
safe to put in a nightly job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from services.domain.degree_fallback import infer_degree, infer_degree_levels
from services.domain.degree_levels import declared_award_levels
from services.ingestion.real_extractor import DeterministicLLMClient
from services.scholarship.freshness import detect_rolling


@dataclass(frozen=True)
class Proposal:
    """One field the document supports filling, with the evidence for it."""

    field: str
    value: Any
    reason: str

    def as_change(self) -> dict[str, Any]:
        """The key ``ReviewService.correct`` expects for this field."""
        return {"application_deadline" if self.field == "deadline" else self.field: self.value}


def _plausible_deadline(value: str, today: date) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return today.year - 1 <= parsed.year <= today.year + 5


def propose_completions(
    *,
    name: str | None,
    official_page_url: str | None,
    degree: str | None,
    degree_levels: list[str],
    funding_type: str | None,
    field_of_study: list[str],
    application_deadline: Any,
    minimum_gpa: float | None,
    minimum_toefl: int | None,
    text: str,
    today: date,
    extractor: DeterministicLLMClient | None = None,
) -> list[Proposal]:
    """Everything the stored document supports and the record is missing.

    Args:
        text: visible text of the document the record was extracted from.
        today: injected so the plausibility window is testable.
    """
    client = extractor or DeterministicLLMClient()
    proposals: list[Proposal] = []

    if application_deadline is None and not detect_rolling(text):
        # Rolling admission is not a missing deadline; it is a page saying the
        # deadline does not apply. Recording a date there would invent a
        # commitment the provider never made.
        value, conflict = client._resolve_deadline(text)
        if value and not conflict and _plausible_deadline(value, today):
            proposals.append(
                Proposal("deadline", value, "the page states one deadline, in a dated sentence")
            )

    if funding_type is None:
        value = client._extract_funding_type(text)
        if value:
            proposals.append(
                Proposal("funding_type", value, "the page states the funding level in a funding sentence")
            )

    if degree is None and not degree_levels:
        single = client._extract_degree(text)
        if single:
            proposals.append(Proposal("degree", single, "the page states one degree level"))
        else:
            levels = declared_award_levels(text)
            if len(levels) > 1:
                proposals.append(
                    Proposal(
                        "degree_levels",
                        levels,
                        "the page lists the award's levels under a level label",
                    )
                )
            else:
                # Evidence the page carries rather than prose it may not have:
                # the programme's own name, and the section its URL lives under.
                inferred = infer_degree(name, official_page_url)
                if inferred:
                    proposals.append(
                        Proposal(
                            "degree",
                            inferred,
                            "the programme name or its URL section names exactly one level",
                        )
                    )
                else:
                    named_levels = infer_degree_levels(name, official_page_url)
                    if named_levels:
                        proposals.append(
                            Proposal(
                                "degree_levels",
                                named_levels,
                                "the programme name names several levels",
                            )
                        )

    if not field_of_study:
        fields = client._extract_fields_of_study(text)
        if fields:
            proposals.append(
                Proposal("field_of_study", fields, "the page names the eligible fields of study")
            )

    if minimum_gpa is None:
        gpa = client._extract_gpa(text)
        if gpa is not None:
            proposals.append(Proposal("minimum_gpa", gpa, "the page states a minimum GPA"))

    if minimum_toefl is None:
        required, score = client._extract_toefl(text)
        if required and score:
            proposals.append(Proposal("minimum_toefl", score, "the page states a TOEFL score"))

    return proposals
