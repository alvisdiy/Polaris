"""The V0.1 catalogue snapshot, measured for the production-cut report."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402

QUERIES = {
    "status": "SELECT extraction_status, count(*) FROM scholarship GROUP BY 1 ORDER BY 2 DESC",
    "countries": """
        SELECT c.name, count(*) FROM scholarship s JOIN country c ON c.country_id = s.country_id
        WHERE s.extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC, 1
    """,
    "providers": """
        SELECT p.provider_name, count(*) FROM scholarship s
        JOIN provider p ON p.provider_id = s.provider_id
        WHERE s.extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC, 1
    """,
    "degrees": """
        SELECT coalesce(degree, '(not stated)'), count(*) FROM scholarship
        WHERE extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC
    """,
    "funding": """
        SELECT coalesce(funding_type, '(not stated)'), count(*) FROM scholarship
        WHERE extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC
    """,
    "reviewed": """
        SELECT coalesce(reviewed_by, '(no reviewer recorded)'), count(*) FROM scholarship
        WHERE extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC
    """,
    "with_source": """
        SELECT count(*) FROM scholarship WHERE extraction_status='approved'
          AND application_url IS NOT NULL
    """,
    "with_deadline": """
        SELECT count(DISTINCT s.scholarship_id) FROM scholarship s
        JOIN scholarship_timeline t ON t.scholarship_id = s.scholarship_id
        WHERE s.extraction_status='approved' AND t.application_deadline IS NOT NULL
    """,
    "last_verified": """
        SELECT count(*) FROM scholarship
        WHERE extraction_status='approved' AND last_verified_at IS NOT NULL
    """,
    "totals": """
        SELECT (SELECT count(*) FROM scholarship) AS scholarships,
               (SELECT count(*) FROM scholarship WHERE extraction_status='approved') AS approved,
               (SELECT count(*) FROM provider) AS providers,
               (SELECT count(*) FROM source_registry) AS sources,
               (SELECT count(*) FROM raw_document) AS documents,
               (SELECT count(*) FROM scholarship_version) AS versions,
               (SELECT count(*) FROM scholarship_review_action) AS review_actions,
               (SELECT count(*) FROM scholarship_candidate_revision) AS candidates
    """,
}


def main() -> None:
    session = SessionLocal()
    try:
        for label, sql in QUERIES.items():
            print(f"\n=== {label}")
            for row in session.execute(text(sql)).mappings().all():
                print("   ", dict(row))
    finally:
        session.close()


if __name__ == "__main__":
    main()

