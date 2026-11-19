"""Post-M10 Priority A — human review of the 8 M10 pilot PENDING_REVIEW records.

Every decision below was taken by opening the official source and comparing it
to what Polaris stored. The reviewer notes carry the evidence, so the reason is
readable months later without re-fetching the page.

Nothing here writes ``extraction_status`` directly. Every transition goes
through :class:`ReviewService`, so each decision writes its review action,
its version row and its current-value provenance together.

Reviewer: post-m10-curation. Run with --apply to commit; the default is a dry
run that prints the decisions it would make.
"""

from __future__ import annotations

import argparse

from database.models.scholarship import Scholarship
from database.session import SessionLocal
from services.review.publication import is_published
from services.review.service import ReviewService

ACTOR = "post-m10-reviewer"

# Each entry is (scholarship_id, decision, reason).
#
# "reject" is used for exactly two evidence-based situations:
#   - the page is an index / overview listing several opportunities rather
#     than one, so there is no single scholarship to publish;
#   - the opportunity is real but outside what this knowledge base is for.
#
# "needs_correction" is used where the scholarship is real but the official
# page yields nothing to verify the blocked fields from.
DECISIONS = [
    (
        "f9edcadd-d6f8-40ce-a6cb-4433f89bacf7",
        "reject",
        "Official page (hisf.or.jp/en/scholarship/oversea/) is an index of five "
        "separate Honjo-funded programmes run by partner universities (USC "
        "IBEAR MBA, UH Misawa-Honjo, JMSA-Honjo, JAA-Honjo, Columbia-Honjo). "
        "'Scholarship Partners Overseas' names that category, not one "
        "scholarship. Publishing it would present a list heading as an "
        "opportunity a student could apply to.",
    ),
    (
        "ac00c8a3-e44a-4edb-9c92-220e01b6509a",
        "reject",
        "Official page (studyinjapan.go.jp/en/planning/scholarships/"
        "other-scholarships/) is navigation between scholarship categories "
        "('Other Scholarships', 'School Scholarships and Tuition Fee "
        "Reductions Systems') with links to external search systems. No "
        "single opportunity is described. Cleaner's looks_like_index "
        "correctly classified it as an index.",
    ),
    (
        "04b5b718-c98f-4753-816b-0286180fae3c",
        "needs_correction",
        "The opportunity is real: the page title is exactly 'Japanese "
        "Government (MEXT) Scholarship' on jasso.go.jp, the official JASSO "
        "page for the MEXT programme. But the page body renders via "
        "JavaScript and yields no degree level, benefit, deadline or "
        "eligibility text, so nothing on the page can verify the fields the "
        "publication gate blocks on. The programme is also an umbrella "
        "covering several degree levels, so a single degree value would be a "
        "fabrication. Held out of publication until a machine-readable "
        "official source is acquired.",
    ),
    (
        "0c140daa-6724-43f2-a23c-72786226c5b2",
        "reject",
        "Official page is a 661-item search-results listing "
        "(studyinjapan.go.jp tuition-reduction_search.php). 'ASEAN Council of "
        "Japan Alumni (ASCOJA)' is one arbitrary entry from the list, and the "
        "stored funding 'Tuition Only' and field 'Arts' were read from "
        "neighbouring rows rather than from any statement about ASCOJA. Not a "
        "detail page; the extracted values are not attributable to the name.",
    ),
    (
        "47d30272-8f6e-4d07-a6ab-129e9f0a42fc",
        "reject",
        "Official page (hisf.or.jp/scholarship/graduate-school/) is a real, "
        "well-specified scholarship, but it is 日本人大学院生奨学金 — for "
        "Japanese nationals already enrolled in or entering a Japanese "
        "graduate school (日本国籍に限ります). Polaris publishes "
        "opportunities for international students, so this is out of scope "
        "rather than wrong. Recorded for traceability; reopen via a "
        "correction if the product scope changes.",
    ),
    (
        "2f1125b0-60c5-4f91-b244-f96aa544095a",
        "reject",
        "Official page (kyoto-u.ac.jp .../scholarships-for-international-"
        "students) is an overview of how Kyoto University routes several "
        "categories of scholarship (Monbukagakusho Honors, private "
        "foundations, university-nominated), not one opportunity. The stored "
        "name also carries the site-name suffix '| KYOTO UNIVERSITY', which "
        "is an extraction defect recorded separately in Priority B.",
    ),
    (
        "79a42f0b-530d-4d3b-a84d-3405fdf2527e",
        "reject",
        "Official page (kyoto-u.ac.jp/en/education-campus/procedures/"
        "scholarships) is an overview listing MEXT, the JASSO short-term "
        "exchange scholarship, ~90 private-foundation programmes, the Taiwan "
        "Kyoto University Scholarship and the ADB Asian Future Leadership "
        "Scholarship Program. 'Japanese Government (Monbukagakusho: MEXT) "
        "Scholarships' is one section heading among several. Cleaner's "
        "looks_like_index correctly classified it as an index.",
    ),
    (
        "7b293229-13e6-4858-869b-789b3e266fa6",
        "reject",
        "Official page (kyoto-u.ac.jp/en/research/support-scholarship) "
        "returns no readable text on fetch — it is a JS-rendered institutional "
        "'research support and scholarships' landing page, not a scholarship. "
        "There is no opportunity here to publish and nothing to verify.",
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the decisions")
    args = parser.parse_args()

    session = SessionLocal()
    applied = 0
    try:
        service = ReviewService(session)
        for scholarship_id, decision, reason in DECISIONS:
            row = service.get(scholarship_id)
            if row is None:
                print(f"!! {scholarship_id}: not found")
                continue
            if row.extraction_status != "pending_review":
                print(
                    f"-- {scholarship_id}: already "
                    f"{row.extraction_status!r}, skipping "
                    f"({row.scholarship_name!r})"
                )
                continue

            print(f"\n{row.scholarship_name}")
            print(f"  {row.official_page_url}")
            print(f"  -> {decision}")

            if not args.apply:
                print("  (dry run; pass --apply to commit)")
                continue

            if decision == "reject":
                outcome = service.reject(
                    scholarship_id,
                    actor=ACTOR,
                    reason=reason,
                    evidence_url=row.official_page_url,
                )
            elif decision == "needs_correction":
                outcome = service.request_correction(
                    scholarship_id,
                    actor=ACTOR,
                    reason=reason,
                    fields=["degree", "funding_type", "application_deadline"],
                    evidence_url=row.official_page_url,
                )
            else:  # pragma: no cover — table above is exhaustive
                raise SystemExit(f"unknown decision {decision!r}")

            session.commit()
            applied += 1
            print(
                f"  {outcome.previous_state} -> {outcome.new_state} "
                f"(version {outcome.version_id})"
            )

        if args.apply:
            print(f"\ncommitted {applied} review decisions")
            published = (
                session.query(Scholarship)
                .filter(Scholarship.extraction_status == "approved")
                .count()
            )
            print(f"approved records now: {published}")
            leak = [
                s.scholarship_name
                for s in session.query(Scholarship)
                .filter(Scholarship.extraction_status != "approved")
                .all()
                if is_published(s)
            ]
            print(f"publication leaks: {leak or 'none'}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
