"""Phase 2A/2B — resolve the 19 legacy approved records against live sources.

Phase 1 found 28 approved records. Nine were curated through the review
workflow with documents, versions and provenance. The other 19 came from the
M8 seed script: hand-typed ``Fully Funded``, no documents, no versions, no
review actions, and — as Phase 2A established — an ``official_page_url`` that
no longer fetches.

This script writes what the live evidence supports, through ReviewService only:

* every correction records a version row, a ``corrected`` review action and
  field provenance, with the live page as ``evidence_url`` and a reason that
  quotes the page;
* ``funding_type`` is blanked wherever the official page does not state it,
  rather than kept on a developer's word;
* a record whose official page cannot be reached at all is rejected with the
  fetches that failed written into the reason, not silently edited.

Safe to re-run: a second pass finds no field left to change and no rejection
left to make, and reports each one as "NO CHANGE" or "ALREADY REJECTED"
rather than writing twice or raising.

    python scripts/v01_apply_phase2.py --dry-run
    python scripts/v01_apply_phase2.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.scholarship_review_action import ReviewSource  # noqa: E402
from database.session import SessionLocal  # noqa: E402

ACTOR = "v01-ship-review"

# (record name, live official page, funding_type to publish or None to blank,
#  the page's own words that decide it)
CORRECTIONS = [
    (
        "MEXT Scholarship (University Recommendation)",
        "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/",
        "Fully Funded",
        "the scholarship benefit table reads 'Tuition | Exempted' and "
        "'Travel allowance | Round-trip travel expenses (airfare) provided', "
        "with monthly payments of 143,000-145,000 yen, 117,000 yen or "
        "242,000 yen by course type",
    ),
    (
        "MEXT Scholarship for Japanese Studies Students",
        "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/",
        "Fully Funded",
        "the scholarship benefit table reads 'Tuition | Exempted' and "
        "'Travel allowance | Round-trip travel expenses (airfare) provided', "
        "with monthly payments of 143,000-145,000 yen, 117,000 yen or "
        "242,000 yen by course type",
    ),
    (
        "MEXT Scholarship for Research Students",
        "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/",
        "Fully Funded",
        "the scholarship benefit table reads 'Tuition | Exempted' and "
        "'Travel allowance | Round-trip travel expenses (airfare) provided', "
        "with monthly payments of 143,000-145,000 yen, 117,000 yen or "
        "242,000 yen by course type",
    ),
    (
        "MEXT Scholarship for Undergraduate Students",
        "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/",
        "Fully Funded",
        "the scholarship benefit table reads 'Tuition | Exempted' and "
        "'Travel allowance | Round-trip travel expenses (airfare) provided', "
        "with monthly payments of 143,000-145,000 yen, 117,000 yen or "
        "242,000 yen by course type",
    ),
    (
        "LPDP Beasiswa Reguler (Master)",
        "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-reguler/",
        "Fully Funded",
        "the page lists the covered components as 'Biaya Pendidikan, Biaya "
        "Pendaftaran, Biaya SPP/Tuition Fee, Tunjangan Buku, ... Asuransi "
        "Kesehatan, Biaya Hidup Bulanan, Biaya Kedatangan'",
    ),
    (
        "LPDP Beasiswa Reguler (PhD)",
        "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-reguler/",
        "Fully Funded",
        "the page lists the covered components as 'Biaya Pendidikan, Biaya "
        "Pendaftaran, Biaya SPP/Tuition Fee, Tunjangan Buku, ... Asuransi "
        "Kesehatan, Biaya Hidup Bulanan, Biaya Kedatangan' and "
        "'Tunjangan keluarga (khusus doktor)'",
    ),
    (
        "LPDP Beasiswa Perguruan Tinggi Utama Dunia (PTUD)",
        "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-ptud/",
        "Fully Funded",
        "the page lists the covered components as 'Biaya Pendidikan, Biaya "
        "Pendaftaran, Biaya SPP/Tuition Fee, Tunjangan Buku, ... Asuransi "
        "Kesehatan, Biaya Hidup Bulanan, Biaya Kedatangan'",
    ),
    (
        "DAAD Study Scholarships - Master Studies for All Academic Disciplines",
        "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026200",
        None,
        "the page states 'Please note that the DAAD does not cover tuition "
        "fees', so 'Fully Funded' is contradicted by the source",
    ),
    (
        "DAAD Development-Related Postgraduate Courses (EPOS)",
        "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777",
        None,
        "'What can be funded?' lists monthly payments, insurance cover, travel "
        "allowance, rent subsidy and family allowance, and makes no claim "
        "that tuition is covered",
    ),
    (
        "DAAD Helmut-Schmidt-Programme",
        "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026397",
        None,
        "the funding section returned no statement about tuition or what the "
        "award covers, so 'Fully Funded' has no source behind it",
    ),
    (
        "DAAD Research Grants - Doctoral Programmes in Germany",
        "https://www.daad.de/go/en/stipa57742121",
        None,
        "'Value' lists monthly scholarship payments of 1,400 euros, insurance "
        "cover, travel allowance and rent subsidy for a research project, and "
        "no tuition",
    ),
    (
        "DAAD Research Grants - Short-Term Grants",
        "https://www.daad.de/go/en/stipa57742121",
        "Partial Funded",
        "'Value' lists monthly scholarship payments of 1,400 euros, insurance "
        "cover and travel allowance for a research project",
    ),
    (
        "Eiffel Scholarship",
        "https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program",
        None,
        "the programme page carries a call for applications but no statement "
        "of what the award pays for",
    ),
    (
        "Fulbright Foreign Student Program",
        "https://foreign.fulbrightonline.org/about/foreign-student-program",
        None,
        "the page says candidates 'secure their own admission, possible "
        "university funding and tuition awards independently', which does "
        "not support 'Fully Funded'",
    ),
    (
        "Australia Awards",
        "https://australiaawards.com.au/",
        None,
        "the official site states no tuition, stipend or full-funding wording "
        "on the page that was captured",
    ),
]

# No official page could be fetched for these through SafeFetch, so nothing
# about them can be verified and they cannot stay approved.
REJECTIONS = [
    (
        "Chinese Government Scholarship",
        "no official page is reachable through SafeFetch: "
        "https://www.csc.edu.cn/laihua/ and https://www.csc.edu.cn/ both "
        "return HTTP 412 Precondition Failed, and "
        "https://studyinchina.csc.edu.cn/ returns the same. The only "
        "reachable page is a US embassy announcement for one application "
        "year, which is not the programme's official page",
    ),
]


def _funding_reason(name: str, funding: str | None, wording: str) -> str:
    if funding is None:
        return (
            f"official page verified live; {wording}. Clearing funding_type: "
            "the published value came from the seed script with no recorded "
            "source wording, and the official page does not state it"
        )
    return (
        f"official page verified live; {wording}. funding_type "
        f"{funding!r} is supported by that wording"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned writes without touching the database",
    )
    args = parser.parse_args(argv)

    from sqlalchemy import select

    from database.models.scholarship import Scholarship
    from services.review.service import ReviewService

    session = SessionLocal()
    try:
        service = ReviewService(session)

        def find(name: str) -> Scholarship:
            row = session.execute(
                select(Scholarship).where(Scholarship.scholarship_name == name)
            ).scalar_one_or_none()
            if row is None:
                raise SystemExit(f"record not found: {name}")
            return row

        for name, url, funding, wording in CORRECTIONS:
            record = find(name)
            changes: dict[str, object] = {"official_page_url": url}
            if funding != record.funding_type:
                changes["funding_type"] = funding
            if record.official_page_url == url:
                del changes["official_page_url"]
            if not changes:
                print(f"NO CHANGE  {name}")
                continue
            print(f"CORRECT    {name}")
            print(f"  changes  {changes}")
            if args.dry_run:
                continue
            outcome = service.correct(
                str(record.scholarship_id),
                actor=ACTOR,
                changes=changes,
                reason=_funding_reason(name, funding, wording),
                source=ReviewSource.ADMIN_API,
                evidence_url=url,
                requeue=False,
            )
            session.commit()
            print(f"  -> {outcome.action} {outcome.new_state} version={outcome.version_id}")

        for name, reason in REJECTIONS:
            record = find(name)
            if record.extraction_status == "rejected":
                # Re-running after a successful pass must not raise: the state
                # machine refuses rejected -> rejected, which is correct, but
                # an unhandled refusal here would abort the run half way and
                # look like a failure rather than like "already done".
                print(f"ALREADY REJECTED  {name}")
                continue
            print(f"REJECT     {name}")
            if args.dry_run:
                continue
            outcome = service.reject(
                str(record.scholarship_id),
                actor=ACTOR,
                reason=reason,
                source=ReviewSource.ADMIN_API,
                evidence_url=record.official_page_url,
            )
            session.commit()
            print(f"  -> {outcome.action} {outcome.new_state}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
