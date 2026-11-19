"""The last V0.1 curation pass — every decision written down individually.

``v01_curate.py`` applies mechanical rules. This script holds the decisions a
rule cannot make: the judgement about whether a page is one opportunity, and
whether a value the extractor recorded is actually supported by the page text.
Each entry below was checked against the captured document named in
``document_ids``; the reason recorded with the decision says what was seen.

Nothing here writes ``extraction_status`` directly. Every change goes through
``ReviewService`` so the action log keeps the old value, the actor and the
reason — the M9.1 integrity guarantee does not bend for a deadline.

    python scripts/v01_final_curation.py --dry-run
    python scripts/v01_final_curation.py --apply --actor v01-curator

Approve only where the captured page names one specific opportunity and states
what it offers. Correct where the extractor recorded a value the page does not
support. Reject where the page is a section, a catalogue or two instruments in
one record.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.models.scholarship import Scholarship  # noqa: E402
from database.session import SessionLocal  # noqa: E402

ACTOR = "v01-curator"

# Every decision, written by hand after reading the capture. ``corrections`` are
# applied first and requeue the record to pending_review; the approve/reject
# that follows therefore publishes the corrected value, not the extracted one.
DECISIONS: tuple[dict, ...] = (
    {
        "name": "SP Scholarship & SP Engineering Scholarship",
        "verdict": "APPROVE",
        "document_ids": ["63ffcfb5-3a38-4338-a1ca-95d86c01cf4a"],
        "seen": (
            "sp.edu.sg detail page, heading 'SP Scholarship and SP Engineering "
            "Scholarship'. Body states they are merit-based awards for "
            "first-year full-time diploma students with an eligibility list "
            "(Year 1, SPOT programme, leadership, conduct) and one selection "
            "route. One opportunity on one page. The name is the page's own."
        ),
        "degree_note": (
            "eligibility reads 'first-year, full-time diploma course students "
            "in Singapore Polytechnic' — a polytechnic diploma, a level the "
            "controlled degree vocabulary has no value for. ADR-018 declined "
            "to widen it, so degree stays NULL."
        ),
    },
    {
        "name": "SP Undergraduate Scholarship",
        "verdict": "APPROVE",
        "document_ids": ["d5437870-c0b2-4f02-8b3e-3d3b0543aefa"],
        "correction_reason": (
                "The page's Scholarship Benefits section reads 'Full scholarship "
                "award of $30,000 will be given out in three tranches of "
                "$10,000 each across three academic years of undergraduate "
                "studies'. That is a fixed award paid to a student who has "
                "already begun a degree elsewhere, not a statement that all "
                "costs are covered, so 'Fully Funded' overstates it. The "
                "amount is the fact; the vocabulary has no term for a cash "
                "award, so the field is left empty rather than forced."
            ),
        "corrections": {"funding_type": None},
        "seen": (
            "sp.edu.sg detail page, heading 'SP Undergraduate Scholarship'. "
            "Eligibility is stated (Singapore Citizens/PRs, SP Diploma with "
            "Merit, CCA records, leadership, no disciplinary record, "
            "matriculated at a local autonomous university). Real award."
        ),
        "degree_note": (
            "eligibility ends 'Successfully matriculated at a full-time "
            "undergraduate degree programme at any of the six local autonomous "
            "universities'. 'Undergraduate' is not a level; ADR-018 records "
            "why it is not read as Bachelor, so degree stays NULL."
        ),
    },
    {
        "name": "PFP Study Award",
        "verdict": "APPROVE",
        "document_ids": ["41b9d66e-b4cc-4bc1-93b9-7ef102eaf85d"],
        "seen": (
            "sp.edu.sg detail page, heading 'PFP Study Award', with an 'Award "
            "Quantum' section (10 recipients, $370 per academic year) and an "
            "eligibility list (Singaporeans/PRs, enrolled PFP, academic "
            "results, CCA). One award, one page."
        ),
        "degree_note": (
            "eligibility reads 'Enrolled PFP students'. The Polytechnic "
            "Foundation Programme is a pre-university course, not a degree at "
            "all, so no degree level is publishable."
        ),
    },
    {
        "name": "NTU Opportunity Grant (NOG)",
        "verdict": "APPROVE",
        "document_ids": ["def7617b-eb57-4a63-84b6-26cd54efd5ee"],
        "seen": (
            "NTU financial-aid detail page. States 'The NTU Opportunity Grant "
            "provides funding of up to S$10,000 over the course of up to four "
            "years of study' and lists applicant eligibility including "
            "Singapore Citizenship and Year 1 undergraduate status. One award, "
            "one page."
        ),
        "degree_note": (
            "eligibility reads 'Be a full-time undergraduate freshman (Year 1) "
            "from AY2026/AY2027 onwards, excluding medicine programme'. A "
            "Year-1 undergraduate place is a level, not a named degree."
        ),
    },
    {
        "name": "Women in Science Bursary",
        "verdict": "APPROVE",
        "document_ids": ["9c878e3d-e717-4460-902b-422ffe056fe3"],
        "seen": (
            "Loughborough detail page, heading 'Women in Science Bursary'. "
            "States the value ('£1000 per annum'), who it is for (women "
            "applying to study science and science-related degrees), how it is "
            "awarded (statement plus entry qualifications) and a renewal "
            "condition (2:1 or above each year)."
        ),
        "degree_note": (
            "the page body says only 'women applying to study with us at "
            "Loughborough' in science; 'undergraduate' appears in the site "
            "breadcrumb and URL path, not in the award's own eligibility "
            "text. Left NULL rather than inferred from navigation."
        ),
    },
    {
        "name": "Overseas Student Programme Loan/ Travel Award",
        "verdict": "REJECT",
        "document_ids": ["89397d5f-2895-4889-ad3e-06d3e03bf41e"],
        "seen": (
            "NTU page describing two different instruments in one record: a "
            "repayable loan for overseas study and a travel award offsetting "
            "travel, accommodation or living expenses. A loan is not a "
            "scholarship, and a record that carries both cannot be matched on "
            "eligibility or funding without guessing which one the visitor "
            "means."
        ),
    },
    {
        "name": "Financial Aid for Overseas Programmes",
        "verdict": "REJECT",
        "document_ids": ["2f6f94f2-c024-4e58-8a2c-51185c4f335b"],
        "seen": (
            "sp.edu.sg section page introducing FAS for Overseas Programmes. "
            "It describes three separate aids (SPOP funding, Opportunity Fund, "
            "PSEA withdrawal) with different eligibility, and names no single "
            "award. The heading is the section's subject, not an opportunity."
        ),
    },
)


def _load(session) -> list[Scholarship]:
    names = [d["name"] for d in DECISIONS]
    found = (
        session.execute(
            text(
                """
                SELECT s.scholarship_id, s.scholarship_name, s.extraction_status,
                       p.provider_name, c.name AS country_name
                FROM scholarship s
                LEFT JOIN provider p ON p.provider_id = s.provider_id
                LEFT JOIN country  c ON c.country_id  = s.country_id
                WHERE s.scholarship_name = ANY(:names)
                """
            ),
            {"names": names},
        )
        .mappings()
        .all()
    )
    out = []
    for row in found:
        out.append(session.get(Scholarship, row["scholarship_id"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default=ACTOR)
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        parser.error("choose --dry-run or --apply")

    from services.review import ReviewService

    session = SessionLocal()
    try:
        records = {s.scholarship_name: s for s in _load(session)}
        missing = [d["name"] for d in DECISIONS if d["name"] not in records]
        if missing:
            print(f"not found: {missing}")
            return 1

        service = ReviewService(session)
        tally = {"APPROVE": 0, "REJECT": 0, "CORRECT": 0}

        for decision in DECISIONS:
            record = records[decision["name"]]
            savepoint = session.begin_nested()
            try:
                for field, value in (decision.get("corrections") or {}).items():
                    service.correct(
                        str(record.scholarship_id),
                        actor=args.actor,
                        changes={field: value},
                        reason=decision["correction_reason"],
                        evidence_url=record.official_page_url,
                        requeue=True,
                    )
                    tally["CORRECT"] += 1

                if decision["verdict"] == "APPROVE":
                    reason = (
                        "V0.1 final curation, read against capture "
                        f"{decision['document_ids'][0]}. {decision['seen']} "
                        "Funding and deadline are recorded as unknown where "
                        "the page does not state them. Quality override on "
                        "degree: " + decision["degree_note"]
                    )
                    service.approve(
                        str(record.scholarship_id),
                        actor=args.actor,
                        reason=reason,
                        evidence_url=record.official_page_url,
                        # The gate wants a degree level; each of these pages
                        # states eligibility without naming one. Reading
                        # "undergraduate" or "diploma" as Bachelor is exactly
                        # what ADR-018 declined on evidence, so the field stays
                        # NULL and the override carries the wording that caused
                        # it, on both the version and the audit row.
                        override_quality=True,
                    )
                else:
                    service.reject(
                        str(record.scholarship_id),
                        actor=args.actor,
                        reason=(
                            "V0.1 final curation, read against capture "
                            f"{decision['document_ids'][0]}. {decision['seen']} "
                            "Not publishable as one distinct opportunity."
                        ),
                        evidence_url=record.official_page_url,
                    )
                savepoint.commit()
                tally[decision["verdict"]] += 1
                print(f"[{decision['verdict']:7}] {decision['name']}")
            except Exception as exc:  # noqa: BLE001 — one record must not stop the pass
                savepoint.rollback()
                session.expunge_all()
                print(f"  ! {decision['name']!r}: {type(exc).__name__}: {exc}")

        if args.apply:
            session.commit()
        else:
            session.rollback()
        print(f"\n{tally} (dry-run, nothing written)" if not args.apply else f"\n{tally}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)



