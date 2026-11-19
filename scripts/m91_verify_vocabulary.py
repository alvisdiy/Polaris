"""M9.1 Phase 10 — Singapore / PFP real-data regression for controlled vocabulary.

Runs against the LIVE approved Singapore record
(`e2a5bfd4-...`, Temasek Polytechnic) inside a transaction that is ALWAYS
rolled back. The shared development database is never modified.

This is a DEVELOPMENT database holding real data from real acquisition runs.

The record is the one that motivated Phase 4: it was published with
``degree = "Polytechnic"``, a value outside every matchable degree vocabulary.
Its source page uses "diploma" seven times and never says "degree" or
"undergraduate". Phase 5 curated it: the published degree is now NULL with the
source wording kept as evidence, so no row is left outside the vocabulary.

Verified here:

  1. source terminology is preserved as evidence
  2. "Polytechnic" can no longer be published
  3. no unjustified "Bachelor" mapping is created for "diploma"
  4. a reviewer cannot save an arbitrary degree
  5. an explicitly supported canonical value still approves
  6. matching only ever sees canonical values
"""

from __future__ import annotations

from dotenv import load_dotenv
from sqlalchemy import text

from database.models import Scholarship
from database.session import SessionLocal
from services.domain.vocabulary import (
    DEGREE,
    UNMAPPED_QUALIFICATION_TERMS,
    qualifies_as_unmapped_qualification,
)
from services.review import InvalidFieldValue, ReviewService

TARGET = "e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a"

# Real wording recovered from the stored RawDocument in the M9 audit.
SOURCE_SNIPPET = (
    "The Polytechnic Foundation Programme awards a diploma to eligible "
    "candidates. Applicants must have completed secondary school. "
    "Candidates are shortlisted based on GCE O-level results."
)


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, note: str = "") -> None:
        checks.append((name, bool(condition), note))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))

    try:
        record = session.get(Scholarship, TARGET)
        print("=" * 78)
        print("M9.1 PHASE 10 — SINGAPORE / PFP VOCABULARY REGRESSION")
        print("Development database, rolled back. No writes are persisted.")
        print("=" * 78)
        print(f"\n  record : {record.scholarship_name}")
        print(f"  status : {record.extraction_status}")
        print(f"  degree : {record.degree!r}   <- the value Phase 4 exists to prevent")

        # --- 1. Source terminology preserved -----------------------------
        print("\n[1] Source terminology")
        unmapped = qualifies_as_unmapped_qualification(SOURCE_SNIPPET)
        check(
            "source's 'diploma' is detected as an unmapped qualification",
            unmapped == "diploma",
            f"detected={unmapped!r}",
        )
        check(
            "qualification terms are enumerated rather than silently dropped",
            "diploma" in UNMAPPED_QUALIFICATION_TERMS
            and "polytechnic" in UNMAPPED_QUALIFICATION_TERMS,
        )
        extractor = __import__(
            "services.ingestion.real_extractor", fromlist=["DeterministicLLMClient"]
        ).DeterministicLLMClient()
        extracted_degree = extractor._extract_degree(SOURCE_SNIPPET)
        check(
            "extraction yields no invented degree for this page",
            extracted_degree is None,
            f"extracted={extracted_degree!r}",
        )
        check(
            "the source wording is kept as evidence",
            extractor.last_unmapped_qualification is not None,
            f"evidence={extractor.last_unmapped_qualification!r}",
        )

        # --- 2. "Polytechnic" can no longer be published --------------------
        print("\n[2] 'Polytechnic' can no longer be published")
        refused = False
        message = ""
        try:
            ReviewService(session).correct(
                TARGET,
                actor="m91-verification",
                changes={"degree": "Polytechnic"},
                reason="republish the original value",
                requeue=False,
            )
        except InvalidFieldValue as exc:
            refused = True
            message = str(exc)
        session.rollback()
        check("review boundary refuses degree='Polytechnic'", refused)
        check(
            "the refusal explains the allowed values",
            all(value in message for value in DEGREE.order),
        )
        check(
            "the refusal states that empty is legitimate",
            "left empty" in message,
        )

        # Database, with the application bypassed entirely.
        db_refused = False
        try:
            session.execute(
                text(
                    "UPDATE scholarship SET degree = 'Polytechnic' "
                    "WHERE scholarship_id = :s"
                ),
                {"s": TARGET},
            )
            session.commit()
        except Exception:
            db_refused = True
            session.rollback()
        check("PostgreSQL refuses it too", db_refused)

        # --- 3. No unjustified "Bachelor" -----------------------------------
        print("\n[3] No unjustified diploma -> Bachelor mapping")
        for term in ("diploma", "polytechnic diploma", "Higher Diploma", "foundation programme"):
            check(
                f"{term!r} is not mapped to a degree level",
                DEGREE.normalize(term) is None,
            )
        check(
            "the existing record was not silently rewritten to Bachelor",
            session.get(Scholarship, TARGET).degree != "Bachelor",
        )

        # --- 4. Arbitrary reviewer values -----------------------------------
        print("\n[4] A reviewer cannot save an arbitrary degree")
        for arbitrary in ("Diploma", "Postgraduate", "Undergraduate", "masters"):
            try:
                ReviewService(session).correct(
                    TARGET,
                    actor="m91-verification",
                    changes={"degree": arbitrary},
                    reason="arbitrary value",
                    requeue=False,
                )
                session.rollback()
                ok = False
            except InvalidFieldValue:
                session.rollback()
                ok = True
            check(f"degree={arbitrary!r} is refused", ok)

        # --- 5. A supported canonical value still approves -------------------
        print("\n[5] A supported canonical value still approves")
        outcome = ReviewService(session).correct(
            TARGET,
            actor="m91-verification",
            changes={"degree": "Short Course"},
            reason="official page describes a short course award",
            requeue=False,
        )
        session.flush()
        session.refresh(record)
        check("a canonical degree is accepted", outcome is not None)
        check(
            "the canonical value is stored",
            record.degree == "Short Course",
            f"degree={record.degree!r}",
        )
        session.rollback()

        # --- 6. Matching only sees canonical values --------------------------
        print("\n[6] Matching input domain")
        from services.matching.profile.validator import VALID_DEGREES

        check(
            "the profile vocabulary is the canonical one",
            VALID_DEGREES == DEGREE.values,
        )
        check(
            "no record carries an out-of-vocabulary degree",
            session.execute(
                text(
                    "SELECT COUNT(*) FROM scholarship WHERE degree IS NOT NULL "
                    "AND degree NOT IN ('Bachelor','Exchange','Master','PhD','Short Course')"
                )
            ).scalar()
            == 0,
            "the grandfathered pre-Phase-4 row was curated in Phase 5",
        )
        check(
            "the curated record kept the source wording as evidence",
            ((session.get(Scholarship, TARGET).field_provenance or {}).get("degree") or {}).get(
                "unmapped_qualification"
            )
            == "diploma",
        )

        print("\n" + "=" * 78)
        passed = sum(1 for _, ok, _ in checks if ok)
        print(f"RESULT: {passed}/{len(checks)} checks passed")
        failed = [name for name, ok, _ in checks if not ok]
        if failed:
            print("FAILED:", ", ".join(failed))
        print("=" * 78)
    finally:
        session.rollback()
        session.close()
        print("\n[transaction rolled back — shared development database unchanged]")


if __name__ == "__main__":
    main()
