"""M9.1 Phase 17 — real-data verification on the Singapore pathway.

Runs the full M9.1 flow against the LIVE approved Singapore record
(`e2a5bfd4-...`, Temasek Polytechnic) inside a transaction that is ALWAYS
rolled back. Nothing is committed; the shared development database keeps its
verified knowledge base exactly as it was.

This is a DEVELOPMENT database, and it holds real data from real acquisition
runs. The check below never writes to it.

Steps verified, in order:

    1. reacquisition of an approved scholarship
    2. published fields remain unchanged
    3. new information becomes reviewable
    4. reviewer approves it
    5. new value becomes public
    6. provenance updates
    7. version increments exactly once
    8. audit action exists
    9. matching sees the approved value
   10. pending records remain invisible to the public API
"""

from __future__ import annotations

from datetime import date

from dotenv import load_dotenv
from sqlalchemy import func, select

from database.models import (
    Scholarship,
    ScholarshipReviewAction,
    ScholarshipTimeline,
    ScholarshipVersion,
)
from database.session import SessionLocal
from services.domain.vocabulary import DEGREE
from services.exploration.acquisition_service import AcquisitionService
from services.review import ReviewService
from services.review.publication import is_published

TARGET = "e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a"
PROPOSED_DEADLINE = date(2029, 9, 9)
PROPOSED_CYCLE = "2029-cycle"


def snapshot(session, sid):
    s = session.get(Scholarship, sid)
    session.refresh(s)
    tl = session.execute(
        select(ScholarshipTimeline).where(ScholarshipTimeline.scholarship_id == sid)
    ).scalar_one_or_none()
    return {
        "status": s.extraction_status,
        "published": is_published(s),
        "deadline": tl.application_deadline if tl else None,
        "cycle": tl.application_cycle if tl else None,
        "deadline_state": s.deadline_state,
        "versions": session.scalar(
            select(func.count())
            .select_from(ScholarshipVersion)
            .where(ScholarshipVersion.scholarship_id == sid)
        ),
        "review_actions": session.scalar(
            select(func.count())
            .select_from(ScholarshipReviewAction)
            .where(ScholarshipReviewAction.scholarship_id == sid)
        ),
        "provenance_deadline": (s.field_provenance or {}).get("deadline"),
    }


def show(label, snap):
    print(f"  {label}")
    for k, v in snap.items():
        if k == "provenance_deadline":
            origin = (v or {}).get("origin")
            doc = (v or {}).get("document_id")
            print(f"      {k}: origin={origin} document_id={doc}")
        else:
            print(f"      {k}: {v}")


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    checks: list[tuple[str, bool]] = []

    def check(name, condition):
        checks.append((name, bool(condition)))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")

    try:
        before = snapshot(session, TARGET)
        print("=" * 78)
        print("M9.1 REAL-DATA VERIFICATION — Singapore (DEVELOPMENT database, rolled back)")
        print("=" * 78)
        print(f"\nTarget: {before['status']} — published={before['published']}")
        show("BEFORE", before)

        assert before["status"] == "approved", "target is not approved"

        record = session.get(Scholarship, TARGET)

        # --- Phase 4 remediation -------------------------------------------
        # This record still carries the pre-Phase-4 degree 'Polytechnic'. The
        # vocabulary CHECK is NOT VALID, which grandfathered the row but still
        # rejects any UPDATE to it — so the record is frozen until a reviewer
        # corrects the degree. That is the intended forcing function, and the
        # correction is the legitimate route: the review boundary, not a
        # migration or a direct UPDATE. Everything below runs after it, in the
        # same rolled-back transaction.
        if not DEGREE.is_valid(record.degree):
            print("\n[0] Phase 4 remediation: correcting the grandfathered degree")
            print(f"    before: degree={record.degree!r}")
            ReviewService(session).correct(
                TARGET,
                actor="m91-verification",
                changes={"degree": None},
                reason=(
                    "source states a polytechnic diploma, which is not a degree "
                    "level Polaris models (ADR-016); recorded as unknown"
                ),
                evidence_url=record.official_page_url,
                requeue=False,
            )
            session.flush()
            session.refresh(record)
            print(f"    after:  degree={record.degree!r} (unknown, source wording preserved)")
            # Re-baseline: the remediation is itself an audited correction and
            # adds a version row, so the before/after comparison below must
            # start from the corrected state or every count looks inflated.
            before = snapshot(session, TARGET)

        # --- 1. Reacquisition -------------------------------------------
        print("\n[1] Reacquisition of the APPROVED scholarship")
        fresh = Scholarship(
            scholarship_name=record.scholarship_name,
            # degree is deliberately not copied: the live record still carries
            # the grandfathered pre-Phase-4 value, and the M9.1 vocabulary
            # constraint now refuses to store it on a new row. This script
            # exercises reacquisition, not degree.
            degree=None,
            funding_type=record.funding_type,
            official_page_url=record.official_page_url,
            provider_id=record.provider_id,
            country_id=record.country_id,
            source_id=record.source_id,
            field_of_study=list(record.field_of_study or []),
        )
        fresh.timeline = ScholarshipTimeline(
            application_deadline=PROPOSED_DEADLINE,
            application_cycle=PROPOSED_CYCLE,
        )
        session.add(fresh)
        session.flush()

        acquisition = AcquisitionService(session)
        candidate = acquisition._merge_reacquisition(
            record, fresh, "Synthetic reacquisition page text for M9.1 verification."
        )
        session.flush()
        print(f"    candidate: {candidate}")

        during = snapshot(session, TARGET)
        show("AFTER REACQUISITION (still pending review)", during)

        # --- 2 & 3. Boundary + reviewable --------------------------------
        check("published deadline unchanged", during["deadline"] == before["deadline"])
        check("published cycle unchanged", during["cycle"] == before["cycle"])
        check("published deadline_state unchanged", during["deadline_state"] == before["deadline_state"])
        check("version count unchanged (no silent bump)", during["versions"] == before["versions"])
        check("still approved / published", during["status"] == "approved" and during["published"])
        check("candidate created for review", candidate is not None)
        check(
            "candidate proposes the new values",
            candidate is not None
            and {c["field"]: c["new"] for c in candidate.proposed_changes}
            == {"application_deadline": PROPOSED_DEADLINE.isoformat(),
                "application_cycle": PROPOSED_CYCLE},
        )

        # --- 10. Pending stays invisible ---------------------------------
        from services.scholarship.repository import ScholarshipRepository

        repo = ScholarshipRepository(session)
        pending_visible = [
            s for s in repo.get_all_approved() if s.extraction_status != "approved"
        ]
        check("no non-approved record visible in public API", not pending_visible)

        # --- 4 & 5. Reviewer approves ------------------------------------
        print("\n[4] Reviewer approves the candidate")
        outcome = ReviewService(session).approve_candidate(
            str(candidate.candidate_id),
            actor="m91-verification",
            reason="M9.1 real-data verification: official page reflects the 2029 cycle",
            evidence_url=record.official_page_url,
        )
        session.flush()
        after = snapshot(session, TARGET)
        show("AFTER REVIEWER APPROVAL", after)
        print(f"    outcome action: {outcome.action}")

        check("new deadline published", after["deadline"] == PROPOSED_DEADLINE)
        check("new cycle published", after["cycle"] == PROPOSED_CYCLE)
        check("still approved after candidate approval", after["status"] == "approved")

        # --- 6. Provenance ------------------------------------------------
        prov = after["provenance_deadline"] or {}
        check(
            "provenance now records the human decision",
            prov.get("origin") == "human_review" and prov.get("actor") == "m91-verification",
        )
        check(
            "provenance not fragmented across two keys",
            "application_deadline" not in (snapshot(session, TARGET) and
                                            session.get(Scholarship, TARGET).field_provenance or {}),
        )
        check(
            "original extraction provenance preserved",
            isinstance(prov.get("previous"), dict)
            and prov["previous"].get("method") == "deterministic_extractor",
        )

        # --- 7 & 8. Version + audit ---------------------------------------
        check(
            "version incremented exactly once",
            after["versions"] == before["versions"] + 1,
        )
        session.refresh(candidate)
        check("candidate closed as approved", candidate.status == "approved")

        actions = (
            session.query(ScholarshipReviewAction)
            .filter(
                ScholarshipReviewAction.scholarship_id == TARGET,
                ScholarshipReviewAction.action.in_(
                    ["candidate_proposed", "candidate_approved"]
                ),
            )
            .all()
        )
        by_action = {a.action: a for a in actions}
        check("audit: candidate_proposed recorded", "candidate_proposed" in by_action)
        check("audit: candidate_approved recorded", "candidate_approved" in by_action)
        if "candidate_approved" in by_action:
            approved_action = by_action["candidate_approved"]
            check(
                "audit action linked to candidate and version",
                str(approved_action.candidate_id) == str(candidate.candidate_id)
                and approved_action.version_id is not None,
            )
            check(
                "audit records the actual field changes",
                {c["field"] for c in (approved_action.field_changes or [])}
                >= {"application_deadline", "application_cycle"},
            )

        # --- 9. Matching sees the approved value ---------------------------
        print("\n[9] Public read + matching see the newly approved value")
        reloaded = repo.get_by_id(TARGET)
        check(
            "repository returns the approved value",
            reloaded.timeline.application_deadline == PROPOSED_DEADLINE,
        )
        check("record still in the public list", TARGET in [
            str(s.scholarship_id) for s in repo.get_all_approved()
        ])

        # --- Stale protection ----------------------------------------------
        print("\n[bonus] Stale-candidate protection")
        from services.review import StaleCandidate

        second = acquisition._merge_reacquisition(
            record,
            _fresh_with(session, record, date(2031, 1, 1), "2031-cycle"),
            "Synthetic reacquisition page text for M9.1 verification.",
        )
        session.flush()
        ReviewService(session).correct(
            TARGET,
            actor="m91-verification",
            changes={"application_cycle": "2030-manual"},
            reason="unrelated manual correction during verification",
            requeue=False,
        )
        session.flush()
        refused = False
        try:
            ReviewService(session).approve_candidate(
                str(second.candidate_id), actor="m91-verification", reason="should refuse"
            )
        except StaleCandidate:
            refused = True
        session.rollback()
        check("stale candidate refused rather than silently applied", refused)

        print("\n" + "=" * 78)
        passed = sum(1 for _, ok in checks if ok)
        print(f"RESULT: {passed}/{len(checks)} checks passed")
        print("=" * 78)
    finally:
        session.rollback()
        session.close()
        print("\n[transaction rolled back — shared development database unchanged]")


def _fresh_with(session, record, deadline, cycle):
    fresh = Scholarship(
        scholarship_name=record.scholarship_name,
        degree=None,
        funding_type=record.funding_type,
        official_page_url=record.official_page_url,
        provider_id=record.provider_id,
        country_id=record.country_id,
        source_id=record.source_id,
        field_of_study=list(record.field_of_study or []),
    )
    fresh.timeline = ScholarshipTimeline(
        application_deadline=deadline, application_cycle=cycle
    )
    session.add(fresh)
    session.flush()
    return fresh


if __name__ == "__main__":
    main()
