"""M11 §2 — where does the existing frontier actually stand?"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402
from services.exploration.acquisition_policy import classify_page  # noqa: E402


def main() -> None:
    session = SessionLocal()
    rows = session.execute(text(
        "SELECT url, state, candidate_type, origin, depth, priority "
        "FROM discovery_frontier"
    )).fetchall()
    print("total frontier rows:", len(rows))

    print("\nby country:")
    for name, n in session.execute(text(
        "SELECT c.iso3, count(*) FROM discovery_frontier f "
        "JOIN country c ON c.country_id = f.country_id "
        "GROUP BY 1 ORDER BY 2 DESC"
    )).fetchall():
        print(f"  {n:>5}  {name}")

    print("\ndepth distribution:", dict(Counter(r[4] for r in rows).most_common()))
    print("priority distribution:", dict(Counter(r[5] for r in rows).most_common()))

    # What does the EXISTING url-level classifier say about the queue?
    by_state_type = Counter()
    pending_assess = Counter()
    for url, state, ctype, origin, depth, priority in rows:
        a = classify_page(url)
        by_state_type[(state, ctype, a.page_type)] += 1
        if state == "pending":
            pending_assess[a.page_type] += 1
    print("\nurl-level classify_page over PENDING queue:", dict(pending_assess))

    print("\nstate x candidate_type x url assessment:")
    for key, n in sorted(by_state_type.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>5}  {key}")

    print("\ntop hosts in pending queue:")
    hosts = Counter()
    for url, state, *_ in rows:
        if state == "pending":
            host = url.split("/")[2] if "://" in url else "?"
            hosts[host] += 1
    for host, n in hosts.most_common(15):
        print(f"  {n:>5}  {host}")
    print("  distinct hosts in pending:", len(hosts))

    session.close()


if __name__ == "__main__":
    main()
