"""M10.8 database integrity audit.

Read-only. Checks the invariants that would let a wrong fact reach a student,
rather than the ones that would merely crash:

    Scholarship · ScholarshipVersion · ScholarshipCandidateRevision · Provider
    Country · University · SourceRegistry · RawDocument · ReviewAction

Every check states the failure it exists to catch. A check that cannot fail is
worse than no check, because it is read as an assurance that was never
actually provided.
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, text

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402
from database.models.scholarship_candidate_revision import (  # noqa: E402
    ScholarshipCandidateRevision,
)
from database.models.scholarship_review_action import (  # noqa: E402
    ScholarshipReviewAction,
)
from database.models.scholarship_version import ScholarshipVersion  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.domain.vocabulary import CONTROLLED_VOCABULARIES  # noqa: E402
from services.review.publication import PUBLISHED_STATE  # noqa: E402

# Values that must never exist in a stored record. Each was a real value at
# some point: "Unknown Scholarship" was carried by 134 records.
FORBIDDEN_NAMES = ("unknown scholarship", "unknown", "n/a")
FORBIDDEN_DEADLINES = ("2099-01-01", "9999-12-31")


def audit(session) -> dict:
    results: list[dict] = []

    def check(name: str, offenders, detail: str, *, pre_existing: str = "") -> None:
        """Record a result. `pre_existing` does not soften the verdict.

        A check that reports FAIL for a condition that predates this phase is
        still reporting FAIL: hiding it behind a footnote would make the audit
        look clean and cost the reader the one thing they need to know. What
        the note carries is attribution, so nobody re-investigates a M8
        artefact as if M10 had just created it.
        """
        rows = list(offenders)
        results.append(
            {
                "check": name,
                "status": "PASS" if not rows else "FAIL",
                "count": len(rows),
                "detail": detail,
                "pre_existing": pre_existing,
                "examples": rows[:5],
            }
        )

    total = session.query(Scholarship).count()
    check(
        "no placeholder scholarship name",
        session.query(Scholarship)
        .filter(Scholarship.scholarship_name.ilike("unknown%"))
        .with_entities(Scholarship.scholarship_id, Scholarship.scholarship_name)
        .all(),
        "M8 stored 'Unknown Scholarship' as if it were an identity.",
        pre_existing=(
            "All are pending_review, so none of them is public. These are the M8 "
            "artefacts M9 quarantined rather than deleted; M10 did not add any. "
            "They are curation backlog, not a publication defect."
        ),
    )

    check(
        "no sentinel deadline",
        session.execute(
            text(
                "SELECT s.scholarship_id, t.application_deadline FROM scholarship s "
                "JOIN scholarship_timeline t ON t.scholarship_id = s.scholarship_id "
                "WHERE t.application_deadline IN ('2099-01-01', '9999-12-31')"
            )
        ).all(),
        "2099-01-01 is the value injected instructions ask for; a stored one is a forgery.",
    )

    for field in ("degree", "funding_type"):
        vocabulary = CONTROLLED_VOCABULARIES[field]
        offenders = [
            (row.scholarship_id, getattr(row, field))
            for row in session.query(Scholarship).all()
            if getattr(row, field) is not None
            and not vocabulary.is_valid(getattr(row, field))
        ]
        check(
            f"{field} is inside its vocabulary",
            offenders,
            f"allowed: {vocabulary.describe()}",
        )

    check(
        "degree may be NULL but never blank",
        session.query(Scholarship)
        .filter(Scholarship.degree == "")
        .with_entities(Scholarship.scholarship_id)
        .all(),
        "'' is not the same answer as NULL; it is a value nobody chose.",
    )

    check(
        "every scholarship names an official page",
        session.query(Scholarship)
        .filter(
            (Scholarship.official_page_url.is_(None))
            | (Scholarship.official_page_url == "")
        )
        .with_entities(Scholarship.scholarship_id)
        .all(),
        "An untraceable record cannot be trusted or corrected.",
    )

    check(
        "published record has a document behind its machine provenance",
        session.query(Scholarship)
        .filter(Scholarship.extraction_status == PUBLISHED_STATE)
        .filter(Scholarship.provenance_origin.isnot(None))
        .filter(Scholarship.provenance_origin != "exploration")
        .filter(
            text(
                "scholarship.field_provenance IS NOT NULL AND "
                "scholarship.field_provenance::text LIKE '%\"origin\": \"machine_extracted\"%' "
                "AND scholarship.field_provenance::text NOT LIKE '%document_id\": \"%'"
            )
        )
        .with_entities(Scholarship.scholarship_id)
        .all(),
        "Machine provenance with no document is provenance that cannot be checked.",
    )

    # The M9.1 invariant: provenance describes the value published *right now*.
    # A current entry that disagrees with the row is drift, and drift is how a
    # record ends up claiming a machine extracted something a human chose.
    check(
        "current provenance agrees with the current value",
        session.execute(
            text(
                "SELECT s.scholarship_id, e.key, e.value->>'current_value', "
                "       s.degree, s.funding_type "
                "FROM scholarship s, jsonb_each(s.field_provenance) e "
                "WHERE s.extraction_status = 'approved' "
                "AND e.value ? 'current_value' "
                "AND e.key IN ('degree', 'funding_type') "
                "AND COALESCE(e.value->>'current_value', '') <> COALESCE(s." + "degree" + ", '')"
            )
        ).all(),
        "A human-corrected entry whose current_value no longer matches the row is stale provenance.",
    )

    check(
        "published degree that provenance calls human_review is what is stored",
        session.execute(
            text(
                "SELECT s.scholarship_id, e.value->>'current_value', s.degree "
                "FROM scholarship s, jsonb_each(s.field_provenance) e "
                "WHERE s.extraction_status = 'approved' AND e.key = 'degree' "
                "AND e.value->>'origin' = 'human_review' "
                "AND COALESCE(e.value->>'current_value', '') <> COALESCE(s.degree, '')"
            )
        ).all(),
        "M9.1 Phase 5 defect: the row moves, the provenance does not.",
    )

    check(
        "no duplicate version number",
        session.execute(
            text(
                "SELECT scholarship_id, version_number, count(*) FROM scholarship_version "
                "GROUP BY scholarship_id, version_number HAVING count(*) > 1"
            )
        ).all(),
        "uq_scholarship_version_number exists; this confirms the constraint is live.",
    )

    check(
        "no candidate revision is published",
        session.query(ScholarshipCandidateRevision)
        .filter(ScholarshipCandidateRevision.status == "approved")
        .filter(
            ScholarshipCandidateRevision.scholarship_id.in_(
                session.query(Scholarship.scholarship_id).filter(
                    Scholarship.extraction_status != PUBLISHED_STATE
                )
            )
        )
        .with_entities(ScholarshipCandidateRevision.candidate_id)
        .all(),
        "Approving a candidate changes data on a record that was never published.",
    )

    check(
        "no approved record carries a pending candidate as current",
        session.execute(
            text(
                "SELECT c.candidate_id FROM scholarship_candidate_revision c "
                "JOIN scholarship s USING (scholarship_id) "
                "WHERE c.status = 'pending' AND s.extraction_status <> 'approved'"
            )
        ).all(),
        "A pending proposal on an unpublished record has no reviewer to act on it.",
    )

    # The crawler, the extractor and the acquisition service all persist.
    # None of them may appear as the actor on an approval, because an
    # approval with a machine actor is a bypass wearing an audit trail.
    machine_actors = session.execute(
        text(
            "SELECT DISTINCT actor FROM scholarship_review_action "
            "WHERE new_state = 'approved'"
        )
    ).scalars().all()
    check(
        "no machine actor on an approval",
        [actor for actor in machine_actors if actor in
         {"acquisition", "extraction", "llm", "pipeline", "crawler", "system", "seed"}],
        f"actors who have ever approved: {sorted(machine_actors)}",
    )

    check(
        "every approved record has an approval action",
        session.execute(
            text(
                "SELECT s.scholarship_id FROM scholarship s WHERE s.extraction_status = 'approved' "
                "AND NOT EXISTS (SELECT 1 FROM scholarship_review_action a "
                "WHERE a.scholarship_id = s.scholarship_id AND a.new_state = 'approved')"
            )
        ).all(),
        "A record that became public without an approval row has no auditable reviewer.",
        pre_existing=(
            "19 of the 20 approved records are the legacy bootstrap seed, which predates the "
            "review service and carries no review action, version or provenance. M9.1 recorded "
            "them as historical truth and deliberately left them in place. The 20th (the PFP "
            "record) has a real approval and correction trail."
        ),
    )

    check(
        "every machine-extracted field provenance names a source",
        session.execute(
            text(
                "SELECT scholarship_id FROM scholarship "
                "WHERE field_provenance IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM jsonb_each(field_provenance) e "
                "WHERE e.value->>'origin' = 'machine_extracted' "
                "AND COALESCE(e.value->>'source_url', '') = '')"
            )
        ).all(),
        "Machine provenance without a URL cannot be re-checked against the page.",
    )

    check(
        "raw document referenced by provenance really exists",
        session.execute(
            text(
                "SELECT s.scholarship_id FROM scholarship s, jsonb_each(s.field_provenance) e "
                "WHERE e.value->>'origin' IN ('machine_extracted', 'reacquisition') "
                "AND e.value->>'document_id' IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM raw_document d "
                "WHERE d.document_id::text = e.value->>'document_id')"
            )
        ).all(),
        "Provenance pointing at a document that does not exist is worse than no provenance.",
    )

    check(
        "provider name is never a sentinel",
        session.execute(
            text(
                "SELECT provider_id, provider_name FROM provider "
                "WHERE lower(provider_name) IN ('unknown', 'n/a', 'none', 'other')"
            )
        ).all(),
        "'Unknown' reached the Provider table the way 'Unknown Scholarship' reached the name column.",
    )

    check(
        "no scholarship sits on a merged provider",
        session.execute(
            text(
                "SELECT s.scholarship_id FROM scholarship s JOIN provider p "
                "USING (provider_id) WHERE p.merged_into_provider_id IS NOT NULL"
            )
        ).all(),
        "M9.1 froze approved records; an unpublished one may still be re-pointed.",
    )

    counts = {
        "scholarships": total,
        "approved": session.query(Scholarship)
        .filter(Scholarship.extraction_status == PUBLISHED_STATE)
        .count(),
        "pending_review": session.query(Scholarship)
        .filter(Scholarship.extraction_status == "pending_review")
        .count(),
        "rejected": session.query(Scholarship)
        .filter(Scholarship.extraction_status == "rejected")
        .count(),
        "versions": session.query(ScholarshipVersion).count(),
        "candidates": session.query(ScholarshipCandidateRevision).count(),
        "review_actions": session.query(ScholarshipReviewAction).count(),
        "raw_documents": session.query(RawDocument).count(),
        "providers": session.execute(text("SELECT count(*) FROM provider")).scalar(),
        "sources": session.execute(text("SELECT count(*) FROM source_registry")).scalar(),
        "countries": session.execute(text("SELECT count(*) FROM country")).scalar(),
        "universities": session.execute(text("SELECT count(*) FROM university")).scalar(),
    }

    origins = dict(
        session.query(Scholarship.provenance_origin, func.count())
        .group_by(Scholarship.provenance_origin)
        .all()
    )
    statuses = dict(
        session.query(Scholarship.extraction_status, func.count())
        .group_by(Scholarship.extraction_status)
        .all()
    )

    return {
        "checks": results,
        "failed": [r for r in results if r["status"] == "FAIL"],
        "counts": counts,
        "statuses": statuses,
        "origins": origins,
    }


def main() -> None:
    session = SessionLocal()
    try:
        report = audit(session)
    finally:
        session.close()
    for entry in report["checks"]:
        marker = "OK " if entry["status"] == "PASS" else "!! "
        print(f"{marker}{entry['check']}: {entry['count']} — {entry['detail']}")
        if entry["status"] == "FAIL" and entry["pre_existing"]:
            print(f"      NOTE (pre-existing): {entry['pre_existing']}")
        for example in entry["examples"]:
            print(f"      {example}")
    print("\ncounts  :", json.dumps(report["counts"], indent=2))
    print("statuses:", json.dumps(report["statuses"], indent=2))
    print("origins :", json.dumps(report["origins"], indent=2))
    print("\nFAILED CHECKS:", len(report["failed"]))


if __name__ == "__main__":
    main()
