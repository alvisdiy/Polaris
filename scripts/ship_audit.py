"""Phase 1 re-audit — the state on disk right now, not what a report claims.

Read-only. Every later phase makes decisions; this one only measures, so that
those decisions rest on the database rather than on the previous report.

    python scripts/ship_audit.py
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402

APPROVED = text(
    """
    SELECT s.scholarship_id, s.scholarship_name, s.degree, s.funding_type,
           s.field_of_study, s.official_page_url, s.application_url,
           s.last_verified_at, s.provenance_origin, s.reviewed_by, s.reviewed_at,
           s.field_provenance, s.quality_report, s.deadline_state,
           s.source_id, s.identity_key,
           p.provider_name, c.name AS country_name,
           (SELECT min(tl.application_deadline) FROM scholarship_timeline tl
             WHERE tl.scholarship_id = s.scholarship_id) AS deadline,
           (SELECT count(*) FROM scholarship_version v
             WHERE v.scholarship_id = s.scholarship_id) AS versions,
           (SELECT count(*) FROM scholarship_review_action ra
             WHERE ra.scholarship_id = s.scholarship_id
               AND ra.action = 'approved') AS approvals,
           (SELECT count(*) FROM raw_document d WHERE d.source_id = s.source_id) AS docs
    FROM scholarship s
    LEFT JOIN provider p ON p.provider_id = s.provider_id
    LEFT JOIN country  c ON c.country_id  = s.country_id
    WHERE s.extraction_status = 'approved'
    ORDER BY (s.reviewed_at IS NULL), s.reviewed_at NULLS LAST, s.scholarship_name
    """
)
COUNTS = {
    "status": "SELECT extraction_status, count(*) FROM scholarship GROUP BY 1 ORDER BY 2 DESC",
    "providers": "SELECT count(*) FROM provider",
    "sources": "SELECT count(*) FROM source_registry",
    "documents": "SELECT count(*) FROM raw_document",
    "versions": "SELECT count(*) FROM scholarship_version",
    "review_actions": "SELECT count(*) FROM scholarship_review_action",
    "candidates": "SELECT count(*) FROM scholarship_candidate_revision",
    "frontier": "SELECT state, count(*) FROM discovery_frontier GROUP BY 1 ORDER BY 2 DESC",
    "frontier_kind": "SELECT candidate_type, count(*) FROM discovery_frontier GROUP BY 1 ORDER BY 2 DESC",
    "frontier_origin": "SELECT origin, count(*) FROM discovery_frontier GROUP BY 1 ORDER BY 2 DESC",
    "frontier_retry": """
        SELECT state, max(retry_count), count(*) FILTER (WHERE retry_count > 0)
        FROM discovery_frontier GROUP BY 1 ORDER BY 1
    """,
    "frontier_pend_age": """
        SELECT min(created_at)::date, max(created_at)::date
        FROM discovery_frontier WHERE state = 'pending'
    """,
    "frontier_dupes": """
        SELECT count(*) FROM (
          SELECT url FROM discovery_frontier GROUP BY url HAVING count(*) > 1
        ) t
    """,
    "source_states": """
        SELECT coalesce(acquisition_state, '(never tried)'), count(*)
        FROM source_registry GROUP BY 1 ORDER BY 2 DESC
    """,
    "source_verification": """
        SELECT coalesce(verification_state, '(unset)'), count(*)
        FROM source_registry GROUP BY 1 ORDER BY 2 DESC
    """,
}


def _provenance_evidence(fp) -> tuple[bool, bool]:
    """(has a document-backed entry, has any entry at all)."""
    if not isinstance(fp, dict) or not fp:
        return False, False
    has_doc = any(
        isinstance(v, dict) and v.get("document_id")
        for v in fp.values()
    )
    return has_doc, True


def main() -> None:
    session = SessionLocal()
    try:
        print("=== counts")
        for label, sql in COUNTS.items():
            rows = session.execute(text(sql)).mappings().all()
            if len(rows) == 1 and len(rows[0]) == 1:
                print(f"  {label:18} {list(rows[0].values())[0]}")
            else:
                print(f"  {label:18} {[tuple(r.values()) for r in rows]}")

        rows = [dict(r) for r in session.execute(APPROVED).mappings()]
    finally:
        session.close()

    print(f"\n=== {len(rows)} approved records")
    header = (
        f"{'name':<46} {'deg':<12} {'funding':<14} {'dl':<11} {'appr':<5} "
        f"{'ver':<4} {'doc':<4} {'lv':<4} {'prov':<5} {'provdoc':<8} {'docs':<4}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        has_doc, has_any = _provenance_evidence(row["field_provenance"])
        name = row["scholarship_name"]
        if len(name) > 44:
            name = name[:41] + "..."
        print(
            f"{name:<46} "
            f"{str(row['degree'] or '-'):<12} "
            f"{str(row['funding_type'] or '-'):<14} "
            f"{str(row['deadline'] or '-'):<11} "
            f"{row['approvals']:<5} "
            f"{row['versions']:<4} "
            f"{'Y' if row['docs'] else 'N':<4} "
            f"{'Y' if row['last_verified_at'] else 'N':<4} "
            f"{'Y' if has_any else 'N':<5} "
            f"{'Y' if has_doc else 'N':<8} "
            f"{row['docs']:<4}"
        )

    print("\n=== roll-ups over the approved set")
    total = len(rows)
    legacy = [r for r in rows if not r["approvals"]]
    with_appr = [r for r in rows if r["approvals"]]
    print(f"  total approved                    {total}")
    print(f"  with an APPROVED review action    {len(with_appr)}")
    print(f"  legacy (no approval action)       {len(legacy)}")
    print(f"  with >=1 version row              {sum(1 for r in rows if r['versions'])}")
    with_any = sum(1 for r in rows if _provenance_evidence(r["field_provenance"])[1])
    with_doc = sum(1 for r in rows if _provenance_evidence(r["field_provenance"])[0])
    print(f"  with any field_provenance         {with_any}")
    print(f"  with document-backed provenance   {with_doc}")
    print(f"  with last_verified_at             {sum(1 for r in rows if r['last_verified_at'])}")
    print(f"  with application_url              {sum(1 for r in rows if r['application_url'])}")
    print(f"  with a usable deadline            {sum(1 for r in rows if r['deadline'])}")
    print(f"  degree NULL                       {sum(1 for r in rows if not r['degree'])}")
    print(f"  funding Fully Funded              {sum(1 for r in rows if r['funding_type'] == 'Fully Funded')}")
    print(f"  funding NULL                      {sum(1 for r in rows if not r['funding_type'])}")

    print("\n=== fully-funded records and their source wording")
    for row in rows:
        if row["funding_type"] != "Fully Funded":
            continue
        fp = row["field_provenance"] or {}
        entry = fp.get("funding_type") if isinstance(fp, dict) else None
        wording = entry.get("source_value") if isinstance(entry, dict) else None
        print(f"  {row['scholarship_name'][:52]:<54} source_value={wording!r}")

    print("\n=== degree NULL records")
    for row in rows:
        if row["degree"]:
            continue
        fp = row["field_provenance"] or {}
        entry = fp.get("degree") if isinstance(fp, dict) else None
        unmapped = entry.get("unmapped_qualification") if isinstance(entry, dict) else None
        print(f"  {row['scholarship_name'][:52]:<54} unmapped={unmapped!r}")

    print("\n=== approved records with no usable deadline")
    for row in rows:
        if row["deadline"]:
            continue
        print(f"  {row['scholarship_name'][:52]:<54} state={row['deadline_state']!r}")


if __name__ == "__main__":
    main()

