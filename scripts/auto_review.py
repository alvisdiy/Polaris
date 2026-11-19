"""Run the deterministic review pass over the pending queue.

    python scripts/auto_review.py --dry-run
    python scripts/auto_review.py --country MY
    python scripts/auto_review.py --json

Each pending record gets one of three outcomes, all decided by rules:

* **approve** — every publication gate passed, the name identifies a programme,
  and the source is official. There is no judgement left to make.
* **reject** — the record cannot become publishable by reading it again: an
  aggregator page, a duplicate, an office homepage, a generic fee policy, or a
  round the page says is closed.
* **hold** — genuinely ambiguous (a required field is missing, or the provider
  is still a hostname). These stay pending with a written reason.

No model is involved, and the same input always produces the same decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models.country import Country  # noqa: E402
from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402
from services.review import InvalidTransition, ReviewService  # noqa: E402
from services.review.auto_review import APPROVE, HOLD, REJECT, decide  # noqa: E402
from services.scholarship.identity import scholarship_identity_key  # noqa: E402


def _page_text(session, scholarship: Scholarship) -> str:
    provenance = scholarship.field_provenance or {}
    for entry in provenance.values():
        if isinstance(entry, dict) and entry.get("document_id"):
            document = session.get(RawDocument, entry["document_id"])
            if document is not None and document.raw_content:
                from scripts.enrich_records import _text_of

                return _text_of(document.raw_content)
    return ""


def run(args) -> int:
    from database.session import SessionLocal

    session = SessionLocal()
    service = ReviewService(session)
    try:
        query = session.query(Scholarship).filter(
            Scholarship.extraction_status == "pending_review"
        )
        if args.country:
            country = session.query(Country).filter_by(iso2=args.country.upper()).first()
            if country is None:
                print(f"unknown country {args.country}", file=sys.stderr)
                return 2
            query = query.filter(Scholarship.country_id == country.country_id)
        rows = query.order_by(Scholarship.created_at).limit(args.limit).all()

        approved_keys = {
            key
            for (key,) in session.query(Scholarship.identity_key)
            .filter(Scholarship.extraction_status == "approved")
            .all()
            if key
        }

        outcomes: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        decisions: list[dict] = []

        for scholarship in rows:
            report = service.evaluate_quality(scholarship)
            stored = (
                scholarship.quality_report
                if isinstance(scholarship.quality_report, dict)
                else {}
            )
            verdict = stored.get("name_verdict") or {}
            key = scholarship.identity_key or scholarship_identity_key(
                scholarship.provider_id,
                scholarship.scholarship_name or "",
                scholarship.country_id,
            )
            text = "" if args.no_page_text else _page_text(session, scholarship)

            decision = decide(
                name=scholarship.scholarship_name,
                provider_name=(
                    scholarship.provider.provider_name if scholarship.provider else None
                ),
                official_page_url=scholarship.official_page_url,
                publishable=report.publishable,
                blocking=list(report.blocking),
                name_accepted=verdict.get("accepted"),
                duplicate_of_approved=bool(key and key in approved_keys),
                page_text=text,
            )
            outcomes[decision.action] += 1
            reasons[f"{decision.action}:{decision.code}"] += 1
            decisions.append(
                {
                    "scholarship_id": str(scholarship.scholarship_id),
                    "name": scholarship.scholarship_name,
                    "action": decision.action,
                    "code": decision.code,
                    "reason": decision.reason,
                }
            )

            label = f"{str(scholarship.scholarship_id)[:8]} {(scholarship.scholarship_name or '')[:52]:<52} {decision.action:<7} {decision.code}"
            if args.dry_run or decision.action == HOLD:
                print(label)
                continue
            try:
                if decision.action == APPROVE:
                    service.approve(
                        str(scholarship.scholarship_id),
                        actor=args.actor,
                        reason=f"deterministic review: {decision.reason}",
                        evidence_url=scholarship.official_page_url,
                    )
                elif decision.action == REJECT:
                    service.reject(
                        str(scholarship.scholarship_id),
                        actor=args.actor,
                        reason=f"deterministic review: {decision.reason}",
                        evidence_url=scholarship.official_page_url,
                    )
                print(label)
            except InvalidTransition as exc:
                session.rollback()
                print("REFUSED", label, "|", str(exc)[:80])
                outcomes["refused"] += 1

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        print("\n=== AUTO REVIEW SUMMARY ===")
        print(f"considered: {len(rows)}")
        for action, count in outcomes.most_common():
            print(f"  {action:<8} {count}")
        print("reasons:")
        for reason, count in reasons.most_common():
            print(f"  {reason:<28} {count}")
        if args.json:
            print(
                json.dumps(
                    {
                        "considered": len(rows),
                        "outcomes": dict(outcomes),
                        "reasons": dict(reasons),
                        "decisions": decisions,
                        "dry_run": args.dry_run,
                    },
                    indent=2,
                )
            )
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="ISO2 filter")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-page-text",
        action="store_true",
        help="Skip reading stored documents (faster, loses the closed-round check)",
    )
    parser.add_argument("--actor", default="auto-review")
    parser.add_argument("--json", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
