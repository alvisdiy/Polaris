"""Real-data smoke check for the public publication boundary (Phase 6).

Read-only. Exercises the live public API against the shared development
database to confirm the curated Singapore record is still served and that no
unpublished record is reachable by id.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from api.app import app

TARGET = "e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a"

UNPUBLISHED_PROBES = {
    "pending_review": "00000000-0000-0000-0000-000000000000",
}


def main() -> None:
    load_dotenv()
    client = TestClient(app)
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, note: str = "") -> None:
        checks.append((name, bool(condition), note))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))

    print("=" * 78)
    print("M9.1 PHASE 6 — PUBLIC PUBLICATION BOUNDARY (live, read-only)")
    print("=" * 78)

    detail = client.get(f"/api/v1/scholarships/{TARGET}")
    check("curated Singapore record is served", detail.status_code == 200, f"status={detail.status_code}")
    if detail.status_code == 200:
        body = detail.json()
        check("degree is null on the public payload", body.get("degree") is None, f"degree={body.get('degree')!r}")

    listing = client.get("/api/v1/scholarships", params={"limit": 100})
    check("public list returns", listing.status_code == 200)
    results = listing.json().get("results", [])

    from database.models.scholarship import Scholarship
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        listed_ids = [r["scholarship_id"] for r in results]
        statuses = {
            str(sid): status
            for sid, status in session.query(
                Scholarship.scholarship_id, Scholarship.extraction_status
            )
            .filter(Scholarship.scholarship_id.in_(listed_ids))
            .all()
        }
        check(
            "every listed record is approved",
            bool(listed_ids) and all(statuses.get(i) == "approved" for i in listed_ids),
            f"{len(listed_ids)} rows served",
        )

        hidden = (
            session.query(Scholarship.scholarship_id)
            .filter(Scholarship.extraction_status != "approved")
            .limit(3)
            .all()
        )
    finally:
        session.close()

    for (sid,) in hidden:
        response = client.get(f"/api/v1/scholarships/{sid}")
        check(
            f"unpublished record {str(sid)[:8]} is a 404 on the public API",
            response.status_code == 404,
            f"status={response.status_code}",
        )

    for label, fake in UNPUBLISHED_PROBES.items():
        response = client.get(f"/api/v1/scholarships/{fake}")
        check(f"{label} id is a 404", response.status_code == 404)

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
