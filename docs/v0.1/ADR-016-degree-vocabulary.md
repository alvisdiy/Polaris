# ADR-016 — Degree Vocabulary and Qualification Semantics

- **Status:** Accepted (M9.1 Phase 4)
- **Date:** 2026-10-02
- **Supersedes:** nothing. Narrows the degree definition in `data-dictionary.md` §"Degree".

## Context

The M9 production-readiness audit found finding #3: a reviewer published
`degree = "Polytechnic"` on an APPROVED scholarship, and the value was accepted
because no boundary validated it. The degree list was independently written in
five places, and had already drifted:

| Location | Degree values |
|---|---|
| `matching/profile/validator.py` | Bachelor, Master, PhD, Exchange, Short Course |
| `ingestion/validator.py` | Bachelor, Master, PhD, Exchange, Short Course |
| `api/schemas.py` (prose) | Bachelor, Master, PhD, Exchange, Short Course |
| `matching/profile/normalizer.py` | aliases → 5 canonical values |
| `ingestion/real_extractor.py` | Bachelor, Master, PhD, **Doctorate**, Exchange, Short Course |

The extractor could emit `"Doctorate"`, which its own validator then rejected —
a round trip that could never succeed.

The triggering record is the approved Singapore exploration result,
`e2a5bfd4-…`, "Polytechnic Foundation Programme (PFP)". The audit established
that the stored `RawDocument` for its source page
(`https://www.tp.edu.sg/.../tp-eng-scholarships/tp-eng-scholarship-2020.html`,
11,729 characters of visible text) contains:

```text
"diploma"          × 7
"degree"           × 0
"undergraduate"    × 0
"polytechnic"      × 4
```

So the extractor failed not because the page lacked information but because the
vocabulary could not represent the terminology the page used.

## The question

Should `"diploma"` map to `"Bachelor"`?

The tempting answer is yes: a Polytechnic Foundation Programme is broadly
undergraduate-level, the record would otherwise be unmatchable, and
`diploma → Bachelor` is a one-line change. It is also wrong.

## Decision

**Option C — preserve the unknown qualification.**

The canonical degree vocabulary is unchanged:

```text
Bachelor · Exchange · Master · PhD · Short Course
```

`"diploma"` is **not** mapped to any degree level. A source that says
"diploma" yields `degree = NULL`, with the source wording preserved as
evidence. A reviewer may not substitute `"Polytechnic"` or any other
out-of-vocabulary string.

`"diploma"`, `"polytechnic"`, `"foundation programme"`, `"certificate"` and
related terms are enumerated in `UNMAPPED_QUALIFICATION_TERMS` so that they can
be *detected* and recorded as evidence rather than silently dropped or
invented.

## Rationale

**The Data Dictionary is the contract and does not include Diploma.**
`data-dictionary.md` types `degree` as `Enum` and lists exactly the five values.
The matching-engine specification requires "Degree valid" as a filter
precondition. Adding a sixth value is a product change to two approved
specifications, not an implementation detail.

**Option A cannot be applied consistently without breaking matching.**
`UserProfile.degree` is validated against the same five values and `VALID_DEGREES`
gates every recommendation request. If `scholarship.degree` gained `Diploma`
while the profile vocabulary did not, a Diploma scholarship would be
unmatchable by every user — strictly worse than an honest unknown. Applying it
to both changes the user-facing profile API, which no specification authorises.

**The distinction is real, not pedantic.** A polytechnic diploma and
foundation programme sit *below* a Bachelor's degree. Collapsing them tells a
student that they already hold a qualification they do not, and offers them
scholarships gated on a degree they have not completed. The same applies to
`Short Course`, which is not a degree at all and is already in the vocabulary —
proof that the domain deliberately admits non-degree categories rather than
requiring every value to be a level of study.

**NULL is already a supported answer.** Migration `b01651cfc4c4` deliberately
made `scholarship.degree` nullable. 73 of 154 rows already carry NULL, and the
quality model already treats a silent source as `UNKNOWN` rather than
`MISSING` — "the source did not say" is a first-class state in this domain.
Option C therefore needs no schema change.

**The honest failure is visible, the invented one is not.** A NULL degree is
visible to a reviewer and to the quality report, and it says precisely what is
known. `"Polytechnic"` looked like knowledge and was not.

## Consequences

- The Singapore PFP record's degree remains unresolved until a reviewer makes a
  deliberate decision. Its current value `"Polytechnic"` is grandfathered by
  the database constraint (see below) and is tracked for correction.
- Matching will not surface that scholarship to a Bachelor-seeking user. That is
  the correct conservative behaviour: a wrong match is worse than a missing one.
- If the product later needs qualification-level matching, the honest shape is a
  separate `qualification` concept (Option B) populated from the evidence this
  decision preserves — not a widening of `degree`.

## Curation decision (M9.1 Phase 5)

The decision this ADR left open has been made, and applied through
`ReviewService.correct()` — never a direct `UPDATE`:

```text
degree                 = NULL
unmapped_qualification = "diploma"     (evidence, not a value)
```

`"Short Course"` was considered and rejected: it is in the vocabulary, but
nothing in the source supports it, and choosing it because it would make the
record matchable is exactly the invented answer this ADR refuses.

The correction keeps the record APPROVED and publicly visible. Its degree
provenance now reads `origin = human_review` with the reviewer, the reason, the
timestamp and the official page, the superseded machine entry under `previous`,
and `unmapped_qualification = "diploma"` so the NULL is legible as a decision
rather than a failed extraction. The retired value `"Polytechnic"` remains
visible in the version and audit rows.

The `NOT VALID` degree CHECK can now be revalidated: no row is left outside the
vocabulary.

## Enforcement

| Boundary | Mechanism |
|---|---|
| Extraction | `services/domain/vocabulary.normalize("degree", …)`; returns None when unrecognised, never a guess. Unmapped terms recorded via `qualifies_as_unmapped_qualification` |
| Review (`correct`, `approve_candidate`) | `vocabulary.validate` in `ReviewService._apply_field_change`; raises `InvalidVocabularyValue` → HTTP 422 |
| Profile validation | imports `DEGREE_VALUES` / `FUNDING_VALUES`; no local list |
| Database | `CHECK (degree IS NULL OR degree IN …)`; `funding_type` validated, `degree` added `NOT VALID` |

The `degree` CHECK is intentionally `NOT VALID`. It enforces every future
insert and update immediately while grandfathering the one existing
out-of-vocabulary row, rather than forcing a silent rewrite of published data —
which would violate the publication boundary Phase 2 established.