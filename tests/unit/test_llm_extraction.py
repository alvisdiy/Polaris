"""Evidence-verified LLM extraction.

The contract under test is the anti-hallucination gate: a value the
model asserts without a verbatim quote in the page is dropped, a
value outside the house rules (IELTS 9.5, an unmapped experience
word, an implausible date) is dropped, and a record with no gaps
never spends an API call.
"""

from __future__ import annotations

from datetime import date

from services.intelligence.extraction import (
    ALL_FIELDS,
    propose_llm_completions,
    quote_in_text,
)

TODAY = date(2026, 11, 24)

PAGE = (
    "The Brightpath Scholars Award covers full tuition and provides accommodation. "
    "Applicants must hold a minimum IELTS score of 6.5 overall. "
    "Interviews will be held on 2027-02-10 and results announced on 2027-03-15. "
    "Prior research experience is preferred but not mandatory. "
    "The programme begins on 2027-09-01."
)


class StubClient:
    """Stands in for GeminiClient; records prompts, returns a canned reply."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts: list[str] = []
        self.calls_made = 0

    def generate_json(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        self.calls_made += 1
        return self.reply


def _current(**overrides):
    current = {field: None for field in ALL_FIELDS}
    current.update(overrides)
    return current


def _good_reply():
    return {
        "minimum_ielts": {
            "value": 6.5,
            "evidence": "Applicants must hold a minimum IELTS score of 6.5 overall.",
        },
        "interview_date": {"value": "2027-02-10", "evidence": "Interviews will be held on 2027-02-10"},
        "result_date": {"value": "2027-03-15", "evidence": "results announced on 2027-03-15"},
        "study_start": {"value": "2027-09-01", "evidence": "The programme begins on 2027-09-01."},
        "research_experience": {
            "value": "Preferred",
            "evidence": "Prior research experience is preferred but not mandatory.",
        },
        "tuition_fee": {"value": True, "evidence": "covers full tuition"},
        "accommodation": {"value": True, "evidence": "provides accommodation"},
    }


class TestAdmission:
    def test_verified_proposals_are_admitted(self):
        client = StubClient(_good_reply())
        proposals = propose_llm_completions(
            current=_current(), text=PAGE, today=TODAY, client=client
        )
        by_field = {p.field: p.value for p in proposals}
        assert by_field["minimum_ielts"] == 6.5
        assert by_field["interview_date"] == "2027-02-10"
        assert by_field["research_experience"] == "Preferred"
        assert by_field["tuition_fee"] is True
        # A verified minimum score implies the requirement itself.
        assert by_field["ielts_required"] is True

    def test_a_fabricated_quote_drops_the_value(self):
        reply = _good_reply()
        reply["minimum_ielts"] = {"value": 7.0, "evidence": "An IELTS band of 7.0 is required."}
        proposals = propose_llm_completions(
            current=_current(), text=PAGE, today=TODAY, client=StubClient(reply)
        )
        assert all(p.field != "minimum_ielts" for p in proposals)
        # And without the score, the implied requirement must not appear either.
        assert all(p.field != "ielts_required" for p in proposals)

    def test_out_of_range_values_are_dropped(self):
        reply = _good_reply()
        reply["minimum_ielts"] = {
            "value": 9.5,
            "evidence": "Applicants must hold a minimum IELTS score of 6.5 overall.",
        }
        reply["research_experience"] = {
            "value": "Mandatory",  # not the controlled vocabulary
            "evidence": "Prior research experience is preferred but not mandatory.",
        }
        reply["study_start"] = {"value": "2035-09-01", "evidence": "The programme begins on 2027-09-01."}
        proposals = propose_llm_completions(
            current=_current(), text=PAGE, today=TODAY, client=StubClient(reply)
        )
        fields = {p.field for p in proposals}
        assert "minimum_ielts" not in fields
        assert "research_experience" not in fields
        assert "study_start" not in fields

    def test_benefit_false_is_never_proposed(self):
        reply = {"travel_ticket": {"value": False, "evidence": "covers full tuition"}}
        proposals = propose_llm_completions(
            current=_current(), text=PAGE, today=TODAY, client=StubClient(reply)
        )
        assert proposals == []

    def test_filled_fields_are_not_asked_about(self):
        client = StubClient(_good_reply())
        proposals = propose_llm_completions(
            current=_current(minimum_ielts=7.0, ielts_required=True),
            text=PAGE,
            today=TODAY,
            client=client,
        )
        assert all(p.field != "minimum_ielts" for p in proposals)
        assert "minimum_ielts" not in client.prompts[0]

    def test_no_gaps_means_no_api_call(self):
        client = StubClient(_good_reply())
        full = {field: True for field in ALL_FIELDS}
        full.update({f: "2027-01-01" for f in ("application_open", "deadline", "interview_date", "result_date", "study_start")})
        full.update({"minimum_ielts": 6.5, "minimum_toefl": 90, "minimum_gpa": 3.0,
                     "work_experience": "Required", "research_experience": "Required",
                     "publication": "Optional"})
        proposals = propose_llm_completions(current=full, text=PAGE, today=TODAY, client=client)
        assert proposals == []
        assert client.calls_made == 0


class TestQuoteMatching:
    def test_whitespace_and_case_differences_still_verify(self):
        assert quote_in_text(PAGE, "applicants   must hold a minimum IELTS score of 6.5 overall.")

    def test_a_tiny_quote_proves_nothing(self):
        assert not quote_in_text(PAGE, "tuition")

    def test_an_absent_quote_fails(self):
        assert not quote_in_text(PAGE, "The deadline is 2027-01-15 for all applicants.")
