"""Evidence-verified LLM extraction for the fields heuristics miss.

The deterministic extractor is good at names, deadlines in dated
sentences and funding labels. It structurally cannot fill the rest:
IELTS/GPA numbers in prose, interview and result dates, whether a
benefit is actually provided or explicitly not, experience
requirements stated in words. Those are exactly the fields this
module asks the model for — and exactly the fields where a hallucinated
value would do the most damage, so admission is strict:

1. **Verbatim evidence or nothing.** Every proposed value must carry
   a quote copied from the page, and a deterministic verifier must
   find that quote in the stored document text (whitespace/case
   normalised). No quote, no proposal — the model cannot assert.
2. **Normalisation against the house rules.** Dates must parse and
   sit in a plausible window; IELTS must be 0–9 in half steps; TOEFL
   0–120; experience levels must be the controlled vocabulary
   (``Required`` / ``Preferred`` / ``Optional`` / ``Not Required``).
   Anything else is dropped, never repaired by guessing.
3. **Only gaps.** A field that already holds a value is never asked
   about. Two documented exceptions, both cases where the stored
   value is known to be extractor silence rather than a fact:
   language-requirement booleans stored as ``False`` with no minimum
   score, and benefit booleans not stored as ``True`` (benefits are
   only ever proposed *towards* True, on a quote that states the
   benefit is provided — silence still proves nothing).

Proposals mirror ``services.enrichment.completion.Proposal`` and are
written by the caller through ``ReviewService.correct``, so an
LLM-filled field carries the same version, audit row and provenance
as a human edit, with the evidence quote in the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from services.domain.vocabulary import EXPERIENCE_VALUES
from services.intelligence.gemini import GeminiClient, LLMUnavailable

MAX_TEXT_CHARS = 24_000
MIN_QUOTE_CHARS = 12

DATE_FIELDS = ("application_open", "deadline", "interview_date", "result_date", "study_start")
EXPERIENCE_FIELDS = ("work_experience", "research_experience", "publication")
BENEFIT_FIELDS = (
    "tuition_fee",
    "monthly_allowance",
    "accommodation",
    "health_insurance",
    "travel_ticket",
    "research_grant",
)
ALL_FIELDS = (
    *DATE_FIELDS,
    "ielts_required",
    "minimum_ielts",
    "toefl_required",
    "minimum_toefl",
    "minimum_gpa",
    *EXPERIENCE_FIELDS,
    *BENEFIT_FIELDS,
)

_FIELD_GUIDANCE = {
    "application_open": "the date applications open, ISO format YYYY-MM-DD",
    "deadline": "the application deadline, ISO format YYYY-MM-DD",
    "interview_date": "the interview date, ISO format YYYY-MM-DD",
    "result_date": "the date results are announced, ISO format YYYY-MM-DD",
    "study_start": "the date the programme/studies start, ISO format YYYY-MM-DD",
    "ielts_required": "true if the page requires IELTS, false if it explicitly says IELTS is not required",
    "minimum_ielts": "the minimum overall IELTS band score (a number like 6.5)",
    "toefl_required": "true if the page requires TOEFL, false if it explicitly says TOEFL is not required",
    "minimum_toefl": "the minimum TOEFL iBT score (a whole number like 90)",
    "minimum_gpa": "the minimum GPA on a 4.0 scale (a number like 3.0)",
    "work_experience": "one of: Required, Preferred, Optional, Not Required",
    "research_experience": "one of: Required, Preferred, Optional, Not Required",
    "publication": "whether a publication is expected: one of Required, Preferred, Optional, Not Required",
    **{field: "true only if the page explicitly states this benefit is provided/covered" for field in BENEFIT_FIELDS},
}


@dataclass(frozen=True)
class LLMProposal:
    """One LLM-proposed field value with its verified evidence quote."""

    field: str
    value: Any
    evidence: str

    def as_change(self) -> dict[str, Any]:
        """The key ``ReviewService.correct`` expects for this field."""
        return {"application_deadline" if self.field == "deadline" else self.field: self.value}


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_text(page_text: str, quote: str) -> bool:
    """Whether the quote really appears in the page (the anti-hallucination gate)."""
    normalized_quote = _normalize_ws(quote)
    if len(normalized_quote) < MIN_QUOTE_CHARS:
        return False
    return normalized_quote in _normalize_ws(page_text)


def _missing_fields(current: dict[str, Any]) -> list[str]:
    wanted: list[str] = []
    for field in ALL_FIELDS:
        value = current.get(field)
        if value is None:
            wanted.append(field)
        elif field in ("ielts_required",) and value is False and current.get("minimum_ielts") is None:
            wanted.append(field)  # stored False here is extractor silence, not a fact
        elif field in ("toefl_required",) and value is False and current.get("minimum_toefl") is None:
            wanted.append(field)
        elif field in BENEFIT_FIELDS and value is not True:
            wanted.append(field)  # benefits may only move towards True, on evidence
    return wanted


def build_prompt(page_text: str, wanted: list[str]) -> str:
    field_lines = "\n".join(f'- "{f}": {_FIELD_GUIDANCE[f]}' for f in wanted)
    return (
        "You extract scholarship facts from the official programme page below. "
        "Rules, in order of importance:\n"
        "1. Use ONLY information stated in the page text. Never infer, never use outside knowledge.\n"
        "2. For every field you answer, copy an exact verbatim quote from the page (at most 200 "
        "characters) that states the fact. If you cannot quote it, answer null for that field.\n"
        "3. Answer null for every field the page does not state.\n"
        "4. Dates in ISO format YYYY-MM-DD; if the page gives a month and year only, answer null.\n\n"
        f"Fields wanted:\n{field_lines}\n\n"
        'Reply with one JSON object: {"field_name": {"value": <value or null>, '
        '"evidence": "<verbatim quote or null>"}, ...} covering exactly the wanted fields.\n\n'
        f"PAGE TEXT:\n{page_text[:MAX_TEXT_CHARS]}"
    )


def _plausible_date(value: Any, today: date, *, past_years: int) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    if not (today.year - past_years <= parsed.year <= today.year + 5):
        return None
    return parsed.isoformat()


def _normalize(field: str, raw: Any, today: date) -> Any:
    """The house-rules check. Returns the cleaned value, or None to drop."""
    if raw is None:
        return None
    if field in DATE_FIELDS:
        return _plausible_date(raw, today, past_years=3 if field == "application_open" else 1)
    if field == "minimum_ielts":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        value = float(raw)
        return value if 0 <= value <= 9 and (value * 2) == int(value * 2) else None
    if field == "minimum_toefl":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        value = int(raw)
        return value if 0 <= value <= 120 and float(raw) == value else None
    if field == "minimum_gpa":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        value = float(raw)
        return value if 0 < value <= 5 else None
    if field in EXPERIENCE_FIELDS:
        return raw if raw in EXPERIENCE_VALUES else None
    if field in BENEFIT_FIELDS:
        return True if raw is True else None  # benefits only ever move towards True
    if field in ("ielts_required", "toefl_required"):
        return raw if isinstance(raw, bool) else None
    return None


def propose_llm_completions(
    *,
    current: dict[str, Any],
    text: str,
    today: date,
    client: GeminiClient,
) -> list[LLMProposal]:
    """Ask the model for the record's missing fields; keep only verified answers.

    ``current`` maps every field in ALL_FIELDS to its stored value
    (None when empty). No missing fields means no API call — the free
    quota is spent only where a gap exists. Raises LLMUnavailable when
    the model cannot answer; the caller stops the LLM pass there.
    """
    wanted = _missing_fields(current)
    if not wanted or not text.strip():
        return []

    reply = client.generate_json(build_prompt(text, wanted))

    proposals: list[LLMProposal] = []
    for field in wanted:
        entry = reply.get(field)
        if not isinstance(entry, dict):
            continue
        value = _normalize(field, entry.get("value"), today)
        evidence = entry.get("evidence")
        if value is None or not isinstance(evidence, str):
            continue
        if not quote_in_text(text, evidence):
            continue  # the model asserted without evidence: dropped, not debated
        proposals.append(LLMProposal(field, value, evidence.strip()))

    # A verified minimum score is itself proof the test is required;
    # record that derivation explicitly rather than leaving the pair
    # inconsistent for the matching engine to trip over.
    proposed = {p.field for p in proposals}
    for score_field, required_field in (
        ("minimum_ielts", "ielts_required"),
        ("minimum_toefl", "toefl_required"),
    ):
        if score_field in proposed and required_field not in proposed:
            if current.get(required_field) is not True:
                source = next(p for p in proposals if p.field == score_field)
                proposals.append(LLMProposal(required_field, True, source.evidence))

    return proposals


__all__ = [
    "ALL_FIELDS",
    "LLMProposal",
    "LLMUnavailable",
    "build_prompt",
    "propose_llm_completions",
    "quote_in_text",
]
