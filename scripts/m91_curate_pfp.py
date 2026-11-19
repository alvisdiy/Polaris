"""M9.1 Phase 5 — the Singapore PFP curation decision, applied and verified.

The live record ``e2a5bfd4-...`` (Polytechnic Foundation Programme) was
published with ``degree = "Polytechnic"``: a value outside every degree
vocabulary, derived from a page that says "diploma" seven times and never says
"degree". Under ADR-016 it is not mapped to any level, and there is no
evidence for calling it a "Short Course" either.

The curation decision, therefore:

    degree                 -> NULL
    unmapped_qualification -> "diploma"   (evidence, not a value)

The change is made through ``ReviewService.correct()`` — never a direct
UPDATE — so it writes the version row, the review action and the field
provenance together, and the record stays APPROVED and publicly visible.

Unlike the other m91_* scripts this one COMMITS: the point is to leave the
development knowledge base with the record actually corrected. It is
idempotent, and prints the full verification either way.
"""

from __future__ import annotations

from dotenv import load_dotenv

from database.models import (
    Scholarship,
    ScholarshipReviewAction,
    ScholarshipVersion,
)
from database.session import SessionLocal
from services.domain.vocabulary import DEGREE, is_valid
from services.review import ReviewService
from services.review.publication import is_published

TARGET = "e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a"
UNMAPPED = "diploma"

REASON = (
    "source describes the qualification as a polytechnic diploma; Polaris has "
    "no degree level for it (ADR-016), so the field is left empty rather than "
    "mapped to an unsupported value"
)
ACTOR = "m91-curation"


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, note: str = "") -> None:
        checks.append((name, bool(condition), note))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))

    record = session.get(Scholarship, TARGET)
    versions_before = session.query(ScholarshipVersion).filter_by(scholarship_id=TARGET).count()
    actions_before = session.query(ScholarshipReviewAction).filter_by(scholarship_id=TARGET).count()

    print("=" * 78)
    print("M9.1 PHASE 5 — SINGAPORE PFP CURATION")
    print("=" * 78)
    print(f"\n  record   : {record.scholarship_name}")
    print(f"  status   : {record.extraction_status} (published={is_published(record)})")
    print(f"  degree   : {record.degree!r}   <- outside the degree vocabulary")
    print(f"  versions : {versions_before}   audit actions: {actions_before}")

    already_curated = record.degree is None
    if already_curated:
        print("\n  already curated: degree is NULL, nothing to write")
    else:
        print("\n[curation] ReviewService.correct(degree -> None) with source evidence")
        outcome = ReviewService(session).correct(
            TARGET,
            actor=ACTOR,
            changes={"degree": None},
            reason=REASON,
            evidence_url=record.official_page_url,
            requeue=False,
            unmapped_qualification={"degree": UNMAPPED},
        )
        session.commit()
        session.expire_all()
        record = session.get(Scholarship, TARGET)
        print(f"  version created: {outcome.version_id}")

    # --- 1. The value ----------------------------------------------------
    print("\n[1] Published value")
    check("degree is NULL", record.degree is None, f"degree={record.degree!r}")
    check(
        "no canonical degree was invented",
        record.degree != "Short Course",
        "not mapped to Short Course (ADR-016 Option C)",
    )

    # --- 2. Source evidence preserved ------------------------------------
    print("\n[2] Source evidence")
    prov = (record.field_provenance or {}).get("degree") or {}
    check(
        "provenance names a human origin",
        prov.get("origin") == "human_review",
        f"origin={prov.get('origin')}",
    )
    check(
        "source wording preserved",
        prov.get("unmapped_qualification") == UNMAPPED,
        f"evidence={prov.get('unmapped_qualification')!r}",
    )
    check(
        "who / why / when recorded",
        bool(prov.get("actor")) and bool(prov.get("reason")) and bool(prov.get("corrected_at")),
    )
    check(
        "evidence URL is the official page",
        prov.get("evidence_url") == record.official_page_url,
    )
    check("current value described by the provenance", prov.get("current_value") is None)

    # --- 3. History preserved, not destroyed -----------------------------
    print("\n[3] History")
    check(
        "previous machine provenance preserved",
        (prov.get("previous") or {}).get("document_id") is not None,
    )
    check(
        "superseded value recorded on the entry",
        prov.get("previous_value") == "Polytechnic",
        f"previous={prov.get('previous_value')!r}",
    )

    audit = (
        session.query(ScholarshipReviewAction)
        .filter(ScholarshipReviewAction.scholarship_id == TARGET)
        .order_by(ScholarshipReviewAction.occurred_at.desc())
        .first()
    )
    degree_changes = [
        c
        for a in session.query(ScholarshipReviewAction).filter_by(scholarship_id=TARGET).all()
        for c in (a.field_changes or [])
        if c.get("field") == "degree"
    ]
    check(
        "audit trail records the retired value",
        any(c.get("previous") == "Polytechnic" for c in degree_changes),
    )
    if not already_curated:
        check(
            "correction is audited as a correction",
            audit is not None and audit.action == "corrected" and audit.actor == ACTOR,
        )
        check(
            "one version was created",
            session.query(ScholarshipVersion).filter_by(scholarship_id=TARGET).count() == versions_before + 1,
        )
        check(
            "one audit action was created",
            session.query(ScholarshipReviewAction).filter_by(scholarship_id=TARGET).count() == actions_before + 1,
        )

    # --- 4. Still published ----------------------------------------------
    print("\n[4] Publication")
    check("still APPROVED", record.extraction_status == "approved", f"status={record.extraction_status}")
    check("still publicly visible", is_published(record))
    from services.scholarship.repository import ScholarshipRepository

    repo = ScholarshipRepository(session)
    listed = [str(s.scholarship_id) for s in repo.get_all_approved()]
    check("record appears in the public list", TARGET in listed)
    check("public read returns a null degree", repo.get_by_id(TARGET).degree is None)

    # --- 5. Matching domain ----------------------------------------------
    print("\n[5] Matching")
    check("published degree is in-vocabulary", is_valid("degree", record.degree), "null is a legitimate value")
    offenders = [
        s.scholarship_id
        for s in session.query(Scholarship).filter(Scholarship.degree.isnot(None)).all()
        if not DEGREE.is_valid(s.degree)
    ]
    check(
        "no scholarship carries an out-of-vocabulary degree",
        not offenders,
        f"offenders={offenders}",
    )

    session.close()

    print("\n" + "=" * 78)
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"RESULT: {passed}/{len(checks)} checks passed")
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print("FAILED:", ", ".join(failed))
    print("=" * 78)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
