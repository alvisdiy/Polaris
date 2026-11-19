# The LLM extraction contract

This file was written during M10.1 as an inventory of the boundary, before
changing anything in it, so that "what can the extractor actually do?" has one
answer rather than five derived from five modules.

M10.1 §1 asks for an inventory of what actually reaches the model and what
actually enters validation, so the boundary is described here in one place
instead of being re-derived from five modules each time it is questioned.

The pipeline, end to end:

    Connector / SafeFetch
        → RawDocument                (services/ingestion/repositories)
        → LoadedDocument             (loader.load)
        → CleanedDocument            (cleaner.clean)
        → untrusted boundary          (untrusted.strip_invisible_content, run
                                       inside clean; wrap_untrusted for any
                                       model-backed client)
        → LLMClient.extract_scholarship
        → ExtractedDocument / ExtractedScholarship   (extractor.py)
        → ValidationReport            (validator.validate)
        → ScholarshipMapper.to_orm     (services/scholarship/mapper.py)
        → Scholarship(extraction_status="pending_review")
        → ReviewService               (approve / reject / correct)

------------------------------------------------------------------
What representation reaches the model
------------------------------------------------------------------

`CleanedDocument.clean_text`: trafilatura main content, extracted from the
page *after* comments, `<script>` and `<style>` bodies have been removed.
Text a reader never sees never reaches extraction.

Alongside it, structural context that prose cannot recover:
`page_title`, `headings` (h1–h3, capped), `anchors` (link labels, capped),
`looks_like_index`, and `hidden_instruction_markers`.

`orchestrator._invoke_client` passes exactly those fields as keyword
arguments. A client declaring only the M8 two-argument signature still works —
the call falls back — which is why the boundary is the ABC, not a
convention.

The page is wrapped by `untrusted.wrap_untrusted` before being handed to a
model-backed client. `DeterministicLLMClient` does not need the wrapper: it
parses with explicit patterns and has no branch that reads a page as an
instruction. The wrapper is what protects a client that does use a model.

------------------------------------------------------------------
What representation enters validation
------------------------------------------------------------------

A plain `dict` of scholarship fields, returned by `extract_scholarship`,
constructed into `ExtractedScholarship` by `orchestrator._as_document`. The
extractor's own metadata travels separately under the `_extraction` key and is
moved into `extraction_meta`; it is never a scholarship field.

`ExtractedScholarship` is `extra="forbid"`. A client returning a key that is
not a field is a *validation failure*, not a silently dropped key. This is
deliberate: dropping `{"extraction_status": "approved"}` quietly would leave
no trace that the model had been handed a decision it cannot make.

------------------------------------------------------------------
The rule the whole boundary exists to enforce
------------------------------------------------------------------

The LLM is an extractor. It may report facts and the evidence for them. It may
not:

    approve · publish · reject · set review state · compute a match score
    rank · decide user eligibility · invent facts · write to the database

Structurally, not by convention:

  * `ExtractedScholarship` has no review or publication field, and refuses
    unknown keys (§M10.1.2).
  * `ScholarshipMapper.to_orm` hardcodes `extraction_status="pending_review"`.
    It has no parameter that could change it.
  * `services/ingestion/` never imports the review service. The containment
    test in `tests/security/test_prompt_injection.py` asserts this by reading
    the source, because a page must not be able to reach the state machine.
  * Matching is deterministic (`services/matching`) and takes no extractor
    output other than the fields below.

------------------------------------------------------------------
Vocabulary, absence, and evidence
------------------------------------------------------------------

Controlled fields go through `services.domain.vocabulary`. The extractor
normalises; the review service validates and refuses. The distinction matters:
normalisation is deterministic and records what it normalised, validation is a
refusal that leaves the reviewer's own input untouched.

Absence stays absence. `degree=None` with `unmapped_qualification="diploma"`
in provenance is the correct answer for a polytechnic diploma; mapping it to
Bachelor would assert a qualification the student does not hold (ADR-016).

Confidence is recorded (`extraction_confidence`, `quality_report`) and never
read as authority. A 0.98 verdict still routes to PENDING_REVIEW.

Provenance records, per field: `source_url`, `document_id`, `extracted_at`,
`method`, `origin`, and — where normalisation changed something — the
`source_value` the page actually used, plus `canonical_value` on the row.
That is what makes "how did 'master's degree' become 'Master'?" answerable.