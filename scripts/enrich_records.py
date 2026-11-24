"""Fill missing scholarship fields from the documents already stored.

Runs the deterministic extractors over each record's stored page and writes the
values the first extraction pass missed. No model, no network by default, and no
overwrites: a field that already has a value is left alone.

    python scripts/enrich_records.py --dry-run
    python scripts/enrich_records.py --state approved
    python scripts/enrich_records.py --country MY --fetch-missing
    python scripts/enrich_records.py --llm --dry-run   # Gemini pass (GEMINI_API_KEY)

Why this exists: the review step was being used to fill empty deadlines and
funding types by hand. That is mechanical work the pipeline can do itself, and
doing it by hand is how a project ends up paying a model to notice a missing
date.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models.country import Country  # noqa: E402
from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402
from services.enrichment.completion import propose_completions  # noqa: E402
from services.intelligence.extraction import propose_llm_completions  # noqa: E402
from services.intelligence.gemini import LLMUnavailable, gemini_from_env  # noqa: E402
from services.review import InvalidFieldValue, InvalidTransition, ReviewService  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _text_of(raw_html: str) -> str:
    """Visible text of a stored document, using the pipeline's own cleaner."""
    from services.ingestion.cleaner import strip_invisible_content

    visible, _ = strip_invisible_content(raw_html)
    try:
        import trafilatura

        text = trafilatura.extract(
            visible, include_comments=False, include_tables=True, no_fallback=False
        )
        if text:
            return text
    except Exception:
        pass
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(visible, "html.parser")
    return soup.get_text("\n")


def _document_of(session, scholarship: Scholarship) -> RawDocument | None:
    provenance = scholarship.field_provenance or {}
    for entry in provenance.values():
        if isinstance(entry, dict) and entry.get("document_id"):
            document = session.get(RawDocument, entry["document_id"])
            if document is not None:
                return document
    return None


def _fetch_text(url: str) -> str | None:
    """Last resort for a record whose document was never stored."""
    import httpx

    try:
        response = httpx.get(
            url, headers={"User-Agent": UA}, timeout=25, follow_redirects=True
        )
    except Exception:
        return None
    if response.status_code >= 400 or not response.text:
        return None
    return _text_of(response.text)


def run(args) -> int:
    from database.session import SessionLocal

    llm_client = None
    llm_active = False
    if args.llm:
        llm_client = gemini_from_env()
        if llm_client is None:
            print(
                "--llm needs a Gemini API key: set GEMINI_API_KEY "
                "(Google AI Studio, free tier is enough)",
                file=sys.stderr,
            )
            return 2
        llm_active = True

    session = SessionLocal()
    service = ReviewService(session)
    try:
        query = session.query(Scholarship)
        if args.state != "all":
            query = query.filter(Scholarship.extraction_status == args.state)
        if args.country:
            country = session.query(Country).filter_by(iso2=args.country.upper()).first()
            if country is None:
                print(f"unknown country {args.country}", file=sys.stderr)
                return 2
            query = query.filter(Scholarship.country_id == country.country_id)
        rows = query.order_by(Scholarship.created_at).limit(args.limit).all()

        today = date.today()
        filled: Counter[str] = Counter()
        skipped_no_document = 0
        refused = 0
        changes: list[dict] = []

        for scholarship in rows:
            document = _document_of(session, scholarship)
            text = ""
            if document is not None and document.raw_content:
                text = _text_of(document.raw_content)
            elif args.fetch_missing and scholarship.official_page_url:
                text = _fetch_text(scholarship.official_page_url) or ""
                if not text:
                    skipped_no_document += 1
                    continue
            else:
                skipped_no_document += 1
                continue

            timeline = scholarship.timeline
            requirement = scholarship.requirement
            proposals = propose_completions(
                name=scholarship.scholarship_name,
                official_page_url=scholarship.official_page_url,
                degree=scholarship.degree,
                degree_levels=[row.degree for row in (scholarship.degree_levels or [])],
                funding_type=scholarship.funding_type,
                field_of_study=list(scholarship.field_of_study or []),
                application_deadline=(timeline.application_deadline if timeline else None),
                minimum_gpa=(requirement.minimum_gpa if requirement else None),
                minimum_toefl=(requirement.minimum_toefl if requirement else None),
                text=text,
                today=today,
            )
            for proposal in proposals:
                line = (
                    f"{str(scholarship.scholarship_id)[:8]} "
                    f"{(scholarship.scholarship_name or '')[:46]:<46} "
                    f"{proposal.field:<15} -> {proposal.value}"
                )
                if args.dry_run:
                    print("WOULD", line)
                    filled[proposal.field] += 1
                    continue
                try:
                    service.correct(
                        str(scholarship.scholarship_id),
                        actor=args.actor,
                        changes=proposal.as_change(),
                        reason=f"deterministic completion: {proposal.reason}",
                        evidence_url=scholarship.official_page_url,
                        requeue=False,
                    )
                except (InvalidTransition, InvalidFieldValue) as exc:
                    refused += 1
                    print("REFUSED", line, "|", str(exc)[:70])
                    continue
                print("FILLED ", line)
                filled[proposal.field] += 1
                changes.append(
                    {
                        "scholarship_id": str(scholarship.scholarship_id),
                        "field": proposal.field,
                        "value": proposal.value,
                        "reason": proposal.reason,
                    }
                )

            # --- LLM pass (opt-in, --llm) ---
            # Gemini reads the same stored document for the fields the
            # deterministic pass cannot fill. A proposal is admitted
            # only with a verbatim evidence quote the verifier finds in
            # the text, and is written through the same correct() path
            # with the quote in the reason. The pass stops at the call
            # budget or when the free quota says no — both are reported,
            # neither is an error in the data.
            if llm_client is not None and llm_active:
                if llm_client.calls_made >= args.llm_max_calls:
                    llm_active = False
                    print(f"LLM budget reached ({args.llm_max_calls} calls); stopping the LLM pass")
                else:
                    benefit = scholarship.benefit
                    current = {
                        "application_open": timeline.application_open if timeline else None,
                        "deadline": timeline.application_deadline if timeline else None,
                        "interview_date": timeline.interview_date if timeline else None,
                        "result_date": timeline.result_date if timeline else None,
                        "study_start": timeline.study_start if timeline else None,
                        "ielts_required": requirement.ielts_required if requirement else None,
                        "minimum_ielts": requirement.minimum_ielts if requirement else None,
                        "toefl_required": requirement.toefl_required if requirement else None,
                        "minimum_toefl": requirement.minimum_toefl if requirement else None,
                        "minimum_gpa": requirement.minimum_gpa if requirement else None,
                        "work_experience": requirement.work_experience if requirement else None,
                        "research_experience": (
                            requirement.research_experience if requirement else None
                        ),
                        "publication": requirement.publication if requirement else None,
                        "tuition_fee": benefit.tuition_fee if benefit else None,
                        "monthly_allowance": benefit.monthly_allowance if benefit else None,
                        "accommodation": benefit.accommodation if benefit else None,
                        "health_insurance": benefit.health_insurance if benefit else None,
                        "travel_ticket": benefit.travel_ticket if benefit else None,
                        "research_grant": benefit.research_grant if benefit else None,
                    }
                    # Fields the deterministic pass just filled are no
                    # longer gaps, in the database or in dry-run alike.
                    for proposal in proposals:
                        key = (
                            "deadline"
                            if proposal.field == "deadline"
                            else proposal.field
                        )
                        if key in current:
                            current[key] = proposal.value
                    try:
                        llm_proposals = propose_llm_completions(
                            current=current, text=text, today=today, client=llm_client
                        )
                    except LLMUnavailable as exc:
                        llm_active = False
                        print(f"LLM unavailable, stopping the LLM pass: {exc}")
                        llm_proposals = []
                    for proposal in llm_proposals:
                        line = (
                            f"{str(scholarship.scholarship_id)[:8]} "
                            f"{(scholarship.scholarship_name or '')[:46]:<46} "
                            f"{proposal.field:<15} -> {proposal.value}"
                        )
                        if args.dry_run:
                            print("WOULD (llm)", line, f'| evidence: "{proposal.evidence[:80]}"')
                            filled[proposal.field] += 1
                            continue
                        try:
                            service.correct(
                                str(scholarship.scholarship_id),
                                actor=args.llm_actor,
                                changes=proposal.as_change(),
                                reason=(
                                    "gemini extraction (evidence-verified): "
                                    f'"{proposal.evidence[:160]}"'
                                ),
                                evidence_url=scholarship.official_page_url,
                                requeue=False,
                            )
                        except (InvalidTransition, InvalidFieldValue) as exc:
                            refused += 1
                            print("REFUSED (llm)", line, "|", str(exc)[:70])
                            continue
                        print("FILLED (llm)", line)
                        filled[proposal.field] += 1
                        changes.append(
                            {
                                "scholarship_id": str(scholarship.scholarship_id),
                                "field": proposal.field,
                                "value": proposal.value,
                                "reason": f"gemini evidence: {proposal.evidence[:160]}",
                            }
                        )

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        print("\n=== ENRICHMENT SUMMARY ===")
        print(f"records considered:  {len(rows)}")
        print(f"without a document:  {skipped_no_document}")
        print(f"refused:             {refused}")
        if llm_client is not None:
            print(f"gemini calls made:   {llm_client.calls_made}")
        for field, count in filled.most_common():
            print(f"  {field:<16} {count}")
        if args.json:
            print(
                json.dumps(
                    {
                        "considered": len(rows),
                        "without_document": skipped_no_document,
                        "refused": refused,
                        "filled": dict(filled),
                        "changes": changes,
                        "dry_run": args.dry_run,
                    },
                    default=str,
                    indent=2,
                )
            )
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="ISO2 filter")
    parser.add_argument(
        "--state", default="pending_review", help="pending_review | approved | all"
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Fetch the official page when no stored document exists",
    )
    parser.add_argument("--actor", default="enrichment")
    parser.add_argument(
        "--llm",
        action="store_true",
        help=(
            "Also run the Gemini pass for fields the deterministic pass cannot "
            "fill (needs GEMINI_API_KEY). Proposals are admitted only with a "
            "verbatim evidence quote verified against the document. Note: "
            "--dry-run still spends API calls, as previewing is the point."
        ),
    )
    parser.add_argument(
        "--llm-max-calls",
        type=int,
        default=50,
        help="Per-run Gemini call budget (free-tier guard; default 50)",
    )
    parser.add_argument(
        "--llm-actor",
        default="llm-enrichment",
        help="Audit-trail actor recorded for LLM-filled fields",
    )
    parser.add_argument("--json", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
