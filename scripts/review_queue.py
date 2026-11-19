"""Review queue operator CLI.

Curation is the publication boundary. This script is a thin operator surface
over ``ReviewService``: it never writes ``extraction_status`` itself, so every
decision still produces the version row and the audit action the service owns.

Usage::

    python scripts/review_queue.py list
    python scripts/review_queue.py list --country JP --limit 30
    python scripts/review_queue.py summary
    python scripts/review_queue.py approve <id> --actor alice --reason "verified" --yes
    python scripts/review_queue.py reject  <id> --actor alice --reason "index page" --yes

Write commands require ``--yes``. A reviewer deciding from a typo is a real
failure mode, and the cost of one extra flag is lower than the cost of an
accidental publication.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _country_id(session, iso2: str | None):
    if not iso2:
        return None
    from database.models.country import Country

    country = (
        session.query(Country).filter(Country.iso2 == iso2.strip().upper()).first()
    )
    if country is None:
        raise SystemExit(f"Unknown country ISO2: {iso2}")
    return str(country.country_id)


def _print_rows(rows: list[dict], total: int) -> None:
    print(f"\nPENDING REVIEW — {total} record(s)\n")
    header = f"{'ID':8}  {'NAME':52}  {'PROVIDER':24}  {'COUNTRY':14}  {'CONF':5}  GATES"
    print(header)
    print("-" * len(header))
    for row in rows:
        name = (row.get("scholarship_name") or "")[:52]
        provider = (row.get("provider_name") or "—")[:24]
        country = (row.get("country") or "—")[:14]
        confidence = row.get("extraction_confidence")
        conf = "—" if confidence is None else f"{confidence:.2f}"
        gates = ", ".join(row.get("blocking_fields") or []) or "none"
        print(
            f"{row['scholarship_id'][:8]:8}  {name:52}  {provider:24}  "
            f"{country:14}  {conf:5}  {gates}"
        )
    print()


def _print_summary(stats: dict, oldest) -> None:
    print("\nCURATION SUMMARY\n")
    print(f"Total:               {stats['total']}")
    print(f"Pending review:      {stats['pending_review']}")
    print(f"Approved:            {stats['approved']}")
    print(f"Rejected:            {stats['rejected']}")
    print(f"Needs correction:    {stats['needs_correction']}")
    print(f"Approval rate:       {stats['approval_rate']}")
    print(f"Rejection rate:      {stats['rejection_rate']}")
    print(f"By origin:           {stats['by_origin']}")
    print(f"Oldest pending:      {_iso(oldest) or '—'}")
    print()


def _resolve_rows(service, *, state: str | None, country_id, limit: int):
    rows, total = service.list_for_review(
        state=state, country_id=country_id, limit=limit
    )
    return [service.queue_summary(row) for row in rows], total


def _run_list(args, session) -> int:
    from services.review import ReviewService

    service = ReviewService(session)
    country_id = _country_id(session, args.country)
    state = None if args.state in (None, "", "all") else args.state
    rows, total = _resolve_rows(
        service, state=state, country_id=country_id, limit=args.limit
    )

    if args.json:
        print(json.dumps({"results": rows, "total": total}, default=str, indent=2))
    else:
        _print_rows(rows, total)
    return 0


def _run_summary(args, session) -> int:
    from sqlalchemy import func

    from database.models.scholarship import Scholarship
    from services.review import ReviewService, ReviewStatus

    service = ReviewService(session)
    country_id = _country_id(session, args.country)
    stats = service.metrics(country_id=country_id)

    query = session.query(func.min(Scholarship.created_at)).filter(
        Scholarship.extraction_status == ReviewStatus.PENDING_REVIEW
    )
    if country_id:
        query = query.filter(Scholarship.country_id == country_id)
    oldest = query.scalar()

    if args.json:
        print(json.dumps({**stats, "oldest_pending": _iso(oldest)}, default=str, indent=2))
    else:
        _print_summary(stats, oldest)
    return 0


def _run_approve(args, session) -> int:
    from services.review import (
        InvalidFieldValue,
        InvalidTransition,
        NotPublishable,
        ReviewService,
        StaleCandidate,
    )

    if not args.yes:
        print("Refusing to publish without --yes.", file=sys.stderr)
        return 2

    service = ReviewService(session)
    try:
        outcome = service.approve(
            args.scholarship_id,
            actor=args.actor,
            reason=args.reason,
            override_quality=args.override,
            evidence_url=args.evidence_url,
        )
        # ReviewService flushes but does not commit; the API layer owns the
        # transaction boundary, and so does this CLI. Without this the process
        # exits, Session.close() rolls the flush back, and the command reports
        # a decision that never reached the database.
        session.commit()
    except (InvalidTransition, NotPublishable, InvalidFieldValue, StaleCandidate) as exc:
        session.rollback()
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    print(
        f"Approved {outcome.scholarship_id} "
        f"({outcome.previous_state} → {outcome.new_state}) by {args.actor}"
    )
    return 0


def _run_reject(args, session) -> int:
    from services.review import InvalidTransition, ReviewService

    if not args.yes:
        print("Refusing to reject without --yes.", file=sys.stderr)
        return 2

    service = ReviewService(session)
    try:
        outcome = service.reject(
            args.scholarship_id,
            actor=args.actor,
            reason=args.reason,
            evidence_url=args.evidence_url,
        )
        session.commit()
    except InvalidTransition as exc:
        session.rollback()
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    print(
        f"Rejected {outcome.scholarship_id} "
        f"({outcome.previous_state} → {outcome.new_state}) by {args.actor}"
    )
    return 0


def _run_correct(args, session) -> int:
    from services.review import InvalidFieldValue, InvalidTransition, ReviewService

    if not args.yes:
        print("Refusing to edit without --yes.", file=sys.stderr)
        return 2

    changes: dict[str, object] = {}
    for raw in args.set or []:
        if "=" not in raw:
            print(f"Refusing: --set expects field=value, got {raw!r}", file=sys.stderr)
            return 2
        field, value = raw.split("=", 1)
        field = field.strip()
        value = value.strip()
        if field in ("field_of_study", "degree_levels"):
            changes[field] = [part.strip() for part in value.split(",") if part.strip()]
        elif field == "deadline":
            changes["application_deadline"] = value or None
        else:
            changes[field] = value or None
    if not changes:
        print("Refusing: pass at least one --set field=value.", file=sys.stderr)
        return 2

    service = ReviewService(session)
    try:
        outcome = service.correct(
            args.scholarship_id,
            actor=args.actor,
            changes=changes,
            reason=args.reason,
            evidence_url=args.evidence_url,
        )
        session.commit()
    except (InvalidTransition, InvalidFieldValue) as exc:
        session.rollback()
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    edited = ", ".join(f"{k}={v!r}" for k, v in changes.items())
    print(
        f"Corrected {outcome.scholarship_id} ({edited}) "
        f"by {args.actor}; state {outcome.previous_state} → {outcome.new_state}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polaris review queue")
    parser.add_argument(
        "--actor",
        default=os.getenv("POLARIS_REVIEWER", "cli"),
        help="Reviewer identity recorded on the audit action (default: POLARIS_REVIEWER or 'cli')",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="List records awaiting a decision")
    listing.add_argument("--state", default="pending_review", help="State, or 'all'")
    listing.add_argument("--country", help="ISO2 country filter")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--json", action="store_true", help="Machine-readable output")
    listing.set_defaults(handler=_run_list)

    summary = sub.add_parser("summary", help="Curation metrics and oldest pending")
    summary.add_argument("--country", help="ISO2 country filter")
    summary.add_argument("--json", action="store_true", help="Machine-readable output")
    summary.set_defaults(handler=_run_summary)

    approve = sub.add_parser("approve", help="Publish a pending record")
    approve.add_argument("scholarship_id")
    approve.add_argument("--reason", default=None)
    approve.add_argument("--evidence-url", default=None)
    approve.add_argument(
        "--override",
        action="store_true",
        help="Override overridable quality fields (the reason is still recorded)",
    )
    approve.add_argument("--yes", action="store_true", help="Confirm the write")
    approve.set_defaults(handler=_run_approve)

    reject = sub.add_parser("reject", help="Reject a pending record")
    reject.add_argument("scholarship_id")
    reject.add_argument("--reason", required=True)
    reject.add_argument("--evidence-url", default=None)
    reject.add_argument("--yes", action="store_true", help="Confirm the write")
    reject.set_defaults(handler=_run_reject)

    correct = sub.add_parser("correct", help="Edit fields with audit and evidence")
    correct.add_argument("scholarship_id")
    correct.add_argument(
        "--set",
        action="append",
        metavar="FIELD=VALUE",
        help="Field edit; repeatable (e.g. --set degree=Master)",
    )
    correct.add_argument("--reason", required=True)
    correct.add_argument("--evidence-url", default=None)
    correct.add_argument("--yes", action="store_true", help="Confirm the write")
    correct.set_defaults(handler=_run_correct)
    return parser


def main(argv=None, *, session=None) -> int:
    args = build_parser().parse_args(argv)

    owns_session = session is None
    if session is None:
        from database.session import SessionLocal

        session = SessionLocal()

    try:
        return args.handler(args, session)
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
