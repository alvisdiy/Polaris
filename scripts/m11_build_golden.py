"""Emit the url -> document_id map the golden discovery dataset needs."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402

URLS = [
    "https://www.cranfield.ac.uk/funding/funding-opportunities/commonwealth-shared-scholarship-scheme",
    "https://www.cranfield.ac.uk/som/funding/cranfield-merit-scholarships",
    "https://www.lboro.ac.uk/study/undergraduate/fees-funding/scholarships/future-leaders-scholarship/",
    "https://www.lboro.ac.uk/study/undergraduate/fees-funding/scholarships/international-excellence-scholarships/",
    "https://www.lboro.ac.uk/study/undergraduate/fees-funding/scholarships/sanctuary-scholarships/",
    "https://www.lboro.ac.uk/arts/scholarships/",
    "https://www.daad.de/en/studying-in-germany/scholarships/daad-scholarships/",
    "https://www.daad.de/en/studying-in-germany/scholarships/information-for-scholarship-applicants/",
    "https://www.daad.de/en/studying-in-germany/scholarships/funding-options/",
    "https://www.hisf.or.jp/en/scholarship/foreigner/faq-en/",
    "https://www.ntu.edu.sg/admissions/undergraduate/scholarships/faqs-on-scholarships",
    "https://www.aminef.or.id/grants-for-indonesians/fulbright-programs/scholarship/",
    "https://www.aminef.or.id/grants-for-indonesians/fulbright-programs/scholarship/fulbright-doctoral-degree-phd-scholarship",
    "https://www.aminef.or.id/grants-for-indonesians/fulbright-programs/fellowships/",
    "https://www.sp.edu.sg/admissions/scholarships-talent-programmes/pfp-study-award",
    "https://www.kyoto-u.ac.jp/en/current/how-to/financial-aid/other-scholarship-opportunities",
]


def main() -> None:
    session = SessionLocal()
    for url in URLS:
        rows = session.execute(
            text(
                "SELECT d.document_id, d.fetched_at, length(d.raw_content) "
                "FROM raw_document d WHERE d.source_url = :u "
                "ORDER BY d.fetched_at DESC"
            ),
            {"u": url},
        ).fetchall()
        if not rows:
            print(f"MISSING {url}")
            continue
        best = max(rows, key=lambda r: r[2])  # the fullest capture of this page
        print(f'{url}\n    {best[0]}  {best[1]}  {best[2]} bytes')
    session.close()


if __name__ == "__main__":
    main()
