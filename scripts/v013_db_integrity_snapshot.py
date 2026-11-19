"""Before/after integrity snapshot for the scholarship tables.

Prints a fingerprint of every row in the tables this phase may touch, so a
change can be accounted for rather than asserted. Compared by diffing two runs.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/v013_db_integrity_snapshot.py > /tmp/before.txt
    ... apply the migration and re-extraction ...
    PYTHONPATH=. .venv/Scripts/python.exe scripts/v013_db_integrity_snapshot.py > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt

Read-only.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text

from database.session import SessionLocal


def main() -> int:
    session = SessionLocal()
    conn = session.connection()

    total = conn.execute(text("SELECT count(*) FROM scholarship")).scalar_one()
    print(f"scholarship rows: {total}")

    for status, count in conn.execute(
        text("SELECT extraction_status, count(*) FROM scholarship GROUP BY 1 ORDER BY 1")
    ):
        print(f"  status {status:18} {count}")

    for status, count in conn.execute(
        text(
            "SELECT coalesce(funding_type,'(null)'), count(*) FROM scholarship "
            "WHERE extraction_status='approved' GROUP BY 1 ORDER BY 1"
        )
    ):
        print(f"  approved funding {status:20} {count}")

    print()
    print("# per-row fingerprint: id | status | name | provider | country | source | funding")
    print("# (identity_key is deliberately excluded: this phase is meant to change it)")
    digest = hashlib.sha256()
    for row in conn.execute(
        text(
            "SELECT scholarship_id, extraction_status, scholarship_name, provider_id, "
            "country_id, source_id, coalesce(funding_type,'~'), coalesce(application_url,'~'), "
            "coalesce(official_page_url,'~'), coalesce(degree,'~'), coalesce(provenance_origin,'~') "
            "FROM scholarship ORDER BY scholarship_id"
        )
    ):
        line = "|".join(str(v) for v in row)
        digest.update(line.encode("utf-8"))
    print(f"content digest: {digest.hexdigest()}")

    print()
    print("# identity coverage")
    null_identity = conn.execute(
        text("SELECT count(*) FROM scholarship WHERE identity_key IS NULL")
    ).scalar_one()
    print(f"  rows without identity_key: {null_identity}")
    print(f"  alembic revision: {conn.execute(text('SELECT version_num FROM alembic_version')).scalar()}")

    pending = conn.execute(
        text("SELECT count(*) FROM scholarship_candidate_revision WHERE status='pending'")
    ).scalar_one()
    print(f"  pending candidate revisions: {pending}")

    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
