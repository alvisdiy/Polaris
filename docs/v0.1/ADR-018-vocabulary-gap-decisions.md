# ADR-018 — Two Vocabulary Gaps That Stay Open

- **Status:** Accepted (post-M10 Priority C)
- **Date:** 2026-10-04
- **Amends:** nothing. Records two decisions ADR-016 left open.
- **Evidence:** `scripts/p10_vocabulary_gap.py`, run against all 269 pages in
  `raw_document`.

## Context

The post-M10 milestone asked two questions:

- **C1** — should `"undergraduate"` become an alias for `Bachelor`?
- **C2** — how should a page saying *"All tuition fees, travel and living
  costs"* be represented, given three canonical funding values?

M10 recorded both by inspection. A controlled vocabulary is not changed on
inspection, so this ADR records the counts and the sentences.

## C1 — `undergraduate` is not an alias for `Bachelor`

### What the corpus says

`undergraduate` appears in **109 of 269** stored documents. Reading the
sentences, almost none of them is a statement about the qualification an
applicant holds:

```text
SOAS   "How to apply for undergraduate study"        ← site navigation
SOAS   "Undergraduate funding"                        ← site navigation
NUS    "their application for undergraduate admission
        to NUS"                                       ← the programme entered
NUS    "matriculating into a full-time undergraduate
        programme at NUS/NTU/SMU/SUTD/SIT"            ← the programme entered
```

### The decisive counter-example is in Polaris's own corpus

The stored page for the **NUS Undergraduate Scholarship**
(`nus.edu.sg/oam/scholarships/scholarships-for-freshmen-singapore-citizens/…`)
states its eligibility as:

```text
local Polytechnic Diploma, International Baccalaureate Diploma,
NUS High School Diploma or equivalent qualifications
```

The **University Engineering Scholarship** on the same site is described as
*"open to local Polytechnic Diploma holders who are matriculating into a
full-time Engineering or Technology-related undergraduate programme"*.

So at the institutions Polaris is acquiring from, `undergraduate` names the
**degree programme the student enters**, while the qualification they **hold**
is a polytechnic diploma. In Singapore `undergraduate` includes the
diploma years that sit below a Bachelor's.

### Decision

**`undergraduate` is not added to `DEGREE.aliases`.** A page that says
"undergraduate" without naming a level yields `degree = NULL`, exactly as
ADR-016 requires for `diploma`.

Mapping it would reproduce, on new records, the precise failure ADR-016 was
written to stop: telling a student they already hold a Bachelor's when their
own source says diploma, and surfacing to them scholarships gated on a
qualification they have not completed.

### Matching impact of the decision

None — which is the point. `degree` carries 20 points and gates the
`FilterEngine`. Records whose degree is unknown are already scored
conservatively against a NULL profile field. Adding the alias would move
recommendations for every record extracted from a Singapore or Indian
institutional page, in the direction of a wrong match, which the matching
specification states is worse than a missing one.

### What would change this decision

Evidence that `undergraduate` is used to mean *specifically* the Bachelor's
level — a stated equivalence on official pages, or a corpus dominated by
Anglo-American universities where the term is unambiguous. Neither holds
today.

## C2 — A comprehensive cost statement is not `Fully Funded`

### What the corpus says

Cost-coverage phrases appear in **25 of 269** stored documents. Only **one**
is an award's own funding value:

```text
Cranfield  "At a glance  Funding value
            All tuition fees, travel and living costs"     ← a scholarship
```

The other 24 are money the student arranges for themselves:

```text
Cranfield  "Lendwise Student Loan … can cover tuition fees and living
            expenses"                                        ← a loan
Cranfield  "confirming that all tuition fees will be paid by the
            sponsor"                                         ← a sponsor letter
```

### Why the taxonomy cannot carry it faithfully

`funding_type` is a three-step ladder — `Fully Funded` > `Partial Funded` >
`Tuition Only` — used ordinally by `ranking/engine.py` and as a binary
criterion by `scoring/engine.py`. It answers *how much of the cost base is
covered*.

The Cranfield sentence enumerates three cost lines. It does not claim that
nothing else is payable, and it does not use the word the ladder is built
around. Mapping it to `Fully Funded` would assert a completeness the page never
stated; the existing aliases for `Fully Funded` are all completeness claims
("fully funded", "complete funding", "full funding") and none of them is a
cost list.

### Where the fact belongs instead

Polaris already models the components as structured benefits, not as one
label: `ScholarshipBenefit.tuition_fee`, `monthly_allowance`,
`accommodation`, `travel_ticket`, `health_insurance`. "Travel and living
costs" is a benefit statement. Promoting it to a `funding_type` would
collapse three modelled fields into one ranked label and lose the detail.

### Decision

**`funding_type` stays NULL for such a page.** The wording is preserved as
`extraction_meta.source_terms.funding_type`, so the reviewer's screen shows
*"All tuition fees, travel and living costs"* next to a NULL, which is a
question to answer rather than an error to hide.

### Matching impact

`funding` is a 5-point binary criterion. A NULL `funding_type` scores 0
against any stated preference, so the award is not falsely presented as fully
funded. After a reviewer confirms the coverage and sets the value, scoring
follows the reviewer's decision.

## Consequences

- No controlled value was added in this milestone. `tests/unit/test_vocabulary_gap_decisions.py`
  pins both outcomes so neither can change by accident.
- Both gaps remain visible rather than closed: a reviewer sees a NULL next to
  the source wording.
- The underlying request — matching on qualification *level* and on
  per-component benefit coverage — is a domain-model change, not a vocabulary
  alias. ADR-016 already recorded the honest shape for the first (a separate
  `qualification` concept). Neither is authorised by any current
  specification, and §12 of the post-M10 brief forbids improvising them here.

## Evidence commands

```bash
PYTHONPATH=. python scripts/p10_vocabulary_gap.py     # counts and sentences
PYTHONPATH=. python -m pytest tests/unit/test_vocabulary_gap_decisions.py
```