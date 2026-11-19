"""Phase 8 — frontier hygiene.

The frontier is the discovery queue, and a queue that is mostly work that can
never succeed is worse than a small queue: it hides the real candidates behind
noise and spends page budget on them. Phase 8 found 510 pending candidates on
social platforms and Wikipedia, admitted by link expansion from university
footer links. None can ever be an official scholarship programme page — a
Facebook post is not a programme's own source, and Wikipedia is an
encyclopedia, not a provider.

They are marked ``rejected`` with the reason written to ``outcome``, never
deleted. That is the distinction the brief cares about: an evidence-backed
rejection is a decision a reviewer can audit and reverse; a deletion is not
observable at all. ``discovery_frontier`` is the audit trail of what discovery
considered, so the rows stay.

The script also re-checks the invariants the rest of the pipeline depends on
and reports them rather than assuming them:

* no row left ``in_progress`` with an expired lease;
* no row rejected without a recorded reason;
* no row failed without a recorded reason.

    python scripts/v01_frontier_hygiene.py --dry-run
    python scripts/v01_frontier_hygiene.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.session import SessionLocal  # noqa: E402

# Domains that cannot host a scholarship programme's own page. Kept as an
# explicit list rather than a heuristic so a rejection can always be explained
# and the list can be argued with.
NEVER_A_PROGRAMME_PAGE = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "t.co",
    "linkedin.com", "youtube.com", "youtu.be", "pinterest.com", "tiktok.com",
    "telegram.org", "reddit.com", "medium.com", "wikipedia.org",
    "wikimedia.org", "wa.me", "t.me", "linktr.ee", "bit.ly", "goo.gl",
    "scholar.google.com", "docs.google.com", "drive.google.com",
    "forms.gle", "docs.googleusercontent.com",
)

REASON = (
    "domain cannot host a scholarship programme's official page: it is a "
    "social platform, an encyclopedia, or a link shortener. Admitted by link "
    "expansion from a university footer, not by a source that describes a "
    "programme. Rejected without deletion so the decision stays auditable"
)


def _host_of(url: str) -> str:
    without_scheme = url.split("://", 1)[-1]
    host = without_scheme.split("/", 1)[0].split("?", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import text

    session = SessionLocal()
    try:
        print("=== invariants")
        invariants = {
            "rows stuck in_progress with an expired lease": (
                "SELECT count(*) FROM discovery_frontier "
                "WHERE state='in_progress' AND lease_expires_at < now()"
            ),
            "rows rejected without a recorded reason": (
                "SELECT count(*) FROM discovery_frontier "
                "WHERE state='rejected' AND (outcome IS NULL OR outcome = '{}')"
            ),
            "rows failed without a recorded reason": (
                "SELECT count(*) FROM discovery_frontier "
                "WHERE state='failed' AND (outcome IS NULL OR outcome = '{}')"
            ),
            "pending rows with a future next_retry_at (waiting on backoff)": (
                "SELECT count(*) FROM discovery_frontier "
                "WHERE state='pending' AND next_retry_at > now()"
            ),
        }
        healthy = True
        for label, sql in invariants.items():
            count = session.execute(text(sql)).scalar()
            print(f"  {label:<58} {count}")
            if count:
                healthy = False

        rows = session.execute(
            text(
                "SELECT candidate_id, url, country_id, depth FROM discovery_frontier "
                "WHERE state='pending' ORDER BY priority, created_at"
            )
        ).all()
        doomed = [
            (cid, url) for cid, url, _c, _d in rows
            if _host_of(url) in NEVER_A_PROGRAMME_PAGE
        ]
        by_host: dict[str, int] = {}
        for _cid, url in doomed:
            host = _host_of(url)
            by_host[host] = by_host.get(host, 0) + 1

        print(f"\n=== pending candidates on non-programme domains: {len(doomed)}")
        for host, count in sorted(by_host.items(), key=lambda kv: -kv[1]):
            print(f"  {host:<34} {count}")

        if args.dry_run:
            print("\ndry run — nothing written")
            return 0

        rejected = 0
        for candidate_id, url in doomed:
            session.execute(
                text(
                    "UPDATE discovery_frontier SET state='rejected', "
                    "outcome = CAST(:o AS jsonb), processed_at = now(), "
                    "updated_at = now(), lease_expires_at = NULL "
                    "WHERE candidate_id = :c AND state = 'pending'"
                ),
                {"o": json.dumps({"reason": REASON, "host": _host_of(url)}),
                 "c": candidate_id},
            )
            rejected += 1
        session.commit()
        print(f"\nrejected {rejected} pending candidates, none deleted")

        print("\n=== frontier after")
        for row in session.execute(
            text("SELECT state, count(*) FROM discovery_frontier GROUP BY 1 ORDER BY 2 DESC")
        ):
            print(f"  {row[0]:<12} {row[1]}")
        return 0 if healthy else 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
