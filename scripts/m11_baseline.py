"""M11 §1 — measured baseline. Every number printed comes from a query."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402


def main() -> None:
    session = SessionLocal()
    one = lambda sql: session.execute(text(sql)).scalar()  # noqa: E731
    rows = lambda sql: session.execute(text(sql)).fetchall()  # noqa: E731

    print("=== records")
    print("total                :", one("SELECT count(*) FROM scholarship"))
    print("by status            :", rows(
        "SELECT extraction_status, count(*) FROM scholarship "
        "GROUP BY 1 ORDER BY 2 DESC"))
    print("approved             :", one(
        "SELECT count(*) FROM scholarship WHERE extraction_status='approved'"))
    print("unknown-name rows    :", one(
        "SELECT count(*) FROM scholarship "
        "WHERE lower(scholarship_name)='unknown scholarship'"))
    print("approved w/o action  :", one(
        "SELECT count(*) FROM scholarship s WHERE s.extraction_status='approved' "
        "AND NOT EXISTS (SELECT 1 FROM scholarship_review_action a "
        "WHERE a.scholarship_id = s.scholarship_id)"))

    print("\n=== supporting tables")
    for label, sql in (
        ("providers", "SELECT count(*) FROM provider"),
        ("sources", "SELECT count(*) FROM source_registry"),
        ("raw documents", "SELECT count(*) FROM raw_document"),
        ("versions", "SELECT count(*) FROM scholarship_version"),
        ("review actions", "SELECT count(*) FROM scholarship_review_action"),
        ("candidates", "SELECT count(*) FROM scholarship_candidate_revision"),
        ("countries", "SELECT count(*) FROM country"),
        ("universities", "SELECT count(*) FROM university"),
        ("frontier rows", "SELECT count(*) FROM discovery_frontier"),
        ("exploration runs", "SELECT count(*) FROM exploration_run"),
    ):
        try:
            print(f"{label:<20}:", one(sql))
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"{label:<20}: ERROR {type(exc).__name__}")

    print("\n=== sources by acquisition state")
    try:
        print(rows("SELECT acquisition_state, count(*) FROM source_registry "
                   "GROUP BY 1 ORDER BY 2 DESC"))
    except Exception:  # noqa: BLE001
        session.rollback()
        print("(no acquisition_state column)")

    print("\n=== sources by page_type")
    try:
        print(rows("SELECT page_type, count(*) FROM source_registry "
                   "GROUP BY 1 ORDER BY 2 DESC"))
    except Exception:  # noqa: BLE001
        session.rollback()
        print("(no page_type column)")

    print("\n=== source verification state")
    try:
        print(rows("SELECT verification_state, count(*) FROM source_registry "
                   "GROUP BY 1 ORDER BY 2 DESC"))
    except Exception:  # noqa: BLE001
        session.rollback()

    print("\n=== frontier")
    try:
        print("by state:", rows("SELECT state, count(*) FROM discovery_frontier "
                                "GROUP BY 1 ORDER BY 2 DESC"))
        print("by type :", rows("SELECT candidate_type, count(*) FROM discovery_frontier "
                                "GROUP BY 1 ORDER BY 2 DESC"))
        print("by origin:", rows("SELECT origin, count(*) FROM discovery_frontier "
                                 "GROUP BY 1 ORDER BY 2 DESC"))
    except Exception:  # noqa: BLE001
        session.rollback()
        print("(frontier unavailable)")

    print("\n=== countries present")
    try:
        print(rows("SELECT country_name, iso_code FROM country ORDER BY country_name"))
    except Exception:  # noqa: BLE001
        session.rollback()

    print("\n=== documents per source host (top 15)")
    try:
        for host, n in rows(
            "SELECT split_part(rtrim(d.source_url, '/'), '/', 3) AS host, count(*) "
            "FROM raw_document d GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
        ):
            print(f"  {n:>4}  {host}")
    except Exception:  # noqa: BLE001
        session.rollback()

    session.close()
    print("\nDB URL:", os.environ.get("DATABASE_URL", "(unset)")[:60])


if __name__ == "__main__":
    main()
