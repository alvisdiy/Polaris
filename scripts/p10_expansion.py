"""Post-M10 Priority H — controlled expansion of the real knowledge base.

M10 piloted ten pages. This widens the batch deliberately rather than by
crawling: a curated list of *specific scholarship detail pages* on official
government, university and provider sites, spread across countries, each run
through the same path the pilot used.

    official page
        → SafeFetch            (robots → URL/DNS → bounded retry → redirects)
        → RawDocument
        → cleaner              (invisible content stripped)
        → untrusted boundary
        → extraction
        → schema validation
        → quality gates
        → provenance
        → PENDING_REVIEW

Nothing is approved. There is deliberately no code path here that could take
one: the point of the expansion is to give a reviewer real records, and
publishing is their decision.

The target list is detail pages, not portals. Priority A showed that portal
and overview pages are where the pipeline's weaknesses live — 6 of the 8 M10
pilot records turned out to be index pages — so expanding over those again
would measure the same failure twice.

    python scripts/p10_expansion.py --dry-run
    python scripts/p10_expansion.py
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.models.source_registry import SourceRegistry  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.exploration.acquisition_service import AcquisitionService  # noqa: E402
from services.ingestion.connectors.generic_connector import (  # noqa: E402
    GenericHTTPConnector,
)
from services.ingestion.orchestrator import run_pipeline  # noqa: E402
from services.ingestion.real_extractor import DeterministicLLMClient  # noqa: E402
from services.ingestion.repositories.raw_document_mapper import (  # noqa: E402
    RawDocumentMapper,
)
from services.ingestion.repositories.raw_document_repository import (  # noqa: E402
    RawDocumentRepository,
)

# Curated official scholarship *detail* pages. Chosen for coverage across
# countries and provider types, not for convenience: a batch drawn from one
# portal would measure that portal.
TARGETS = [
    # United Kingdom — government and university
    ("https://www.gov.uk/government/schemes/chevening-scholarships", "Chevening Scholarships"),
    ("https://www.chevening.org/apply/eligibility/", "Chevening eligibility"),
    ("https://www.commonwealthscholarships.org/", "Commonwealth Scholarships"),
    ("https://www.cranfield.ac.uk/som/funding/cranfield-merit-scholarships", "Cranfield Merit"),  # noqa: E501
    ("https://www.cranfield.ac.uk/funding/funding-opportunities/commonwealth-shared-scholarship-scheme", "Commonwealth Shared"),  # noqa: E501
    ("https://www.lboro.ac.uk/study/undergraduate/fees-funding/scholarships/sanctuary-scholarships/", "Loughborough Sanctuary"),  # noqa: E501
    ("https://www.soas.ac.uk/study/taught/postgraduate/fees-funding/scholarships", "SOAS postgraduate"),
    # United States — federal and university
    ("https://www.fulbrightprogram.org/", "Fulbright Program"),
    ("https://www.chevening.org/asean-chevening-scholarship/", "Chevening ASEAN"),
    # Germany — DAAD
    ("https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/helmut-schmidt-programme/", "Helmut Schmidt"),  # noqa: E501
    ("https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/", "DAAD database"),
    # Japan — government
    ("https://www.studyinjapan.go.jp/en/planning/scholarship/types/mext/", "MEXT scholarship types"),
    ("https://www.jasso.go.jp/en/ryugaku/scholarship_j/kokuhi.html", "MEXT JASSO"),
    ("https://www.studyinjapan.go.jp/en/planning/scholarship/types/other/", "Other scholarship types"),
    # Singapore — institutions
    ("https://nus.edu.sg/oam/scholarships/scholarships-for-freshmen-singapore-citizens/nus-undergraduate-scholarship", "NUS Undergraduate"),  # noqa: E501
    ("https://nus.edu.sg/oam/scholarships/scholarships-for-freshmen-singapore-citizens/nus-sports-scholarship", "NUS Sports"),  # noqa: E501
    ("https://nus.edu.sg/oam/scholarships/scholarships-for-freshmen-singapore-citizens/nus-merit-scholarship", "NUS Merit"),  # noqa: E501
    ("https://www.sp.edu.sg/admissions/scholarships-talent-programmes/pfp-study-award", "SP PFP Study Award"),
    ("https://www.tp.edu.sg/schools-and-courses/students/schools/eng/scholarships/tp-eng-scholars-2026.html", "TP Engineering"),  # noqa: E501
    # Australia
    ("https://www.dfat.gov.au/people-and-culture/scholarships", "DFAT Scholarships"),
    ("https://www.australiaawardsscholarships.gov.au/", "Australia Awards"),
    # Canada
    ("https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/study-canada/vanier-bilingual.html", "Vanier"),  # noqa: E501
    # Netherlands
    ("https://www.educationfinancesearch.gov.nl/", "DUO"),
    ("https://www.nuffic.nl/en/education/scholarships", "Nuffic scholarships"),
    # France
    ("https://www.campus-france.org/en/scholarships", "Campus France"),
    # South Korea
    ("https://www.studyinkorea.go.kr/en/sub/subSchlRange.do", "Study in Korea"),
    # Ireland
    ("https://www.hef.ie/awards/", "HEA awards"),
    # Brazil
    ("https://www.gov.br/mre/pt-br/consulado-miami/bolsas-de-estudo", "MRE Scholarships"),
    # China
    ("https://www.csc.edu.cn/en/", "China Scholarship Council"),
    # Indonesia
    ("https://www.aminef.or.id/grants-for-indonesians/", "AMINEF Grants"),
    ("https://www.aminef.or.id/grants-for-indonesians/fulbright-programs/fellowships/fulbright-visiting-scholar/the-fulbright-kennedy-center-fellowship-for-performing-arts-and-science/", "Kennedy Fellowship"),  # noqa: E501
    # Czechia
    ("https://www.muni.cz/en/", "Masaryk University"),
    # Finland
    ("https://www.finland.fi/en/", "Finlandia"),
    # Sweden
    ("https://studyinsweden.se/", "Study in Sweden"),
    # Norway
    ("https://www.norway.no/en/norway-and-the-world/norway-scholarship/", "Norway Scholarship"),
    # Portugal
    ("https://www.dges.gov.pt/", "DGEst"),
]


@dataclass
class ExpansionMetrics:
    """Priority H §9 — one counter per thing that can go wrong."""

    targets: int = 0
    pages_attempted: int = 0
    pages_acquired: int = 0
    pages_failed: int = 0
    extraction_attempts: int = 0
    extraction_succeeded: int = 0
    schema_failures: int = 0
    quality_failures: int = 0
    duplicates: int = 0
    pending_review: int = 0
    named: int = 0
    nameless: int = 0
    unknown_deadline: int = 0
    unknown_degree: int = 0
    unknown_funding: int = 0
    conflicts: int = 0
    failure_categories: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)

    def fail(self, category: str) -> None:
        self.failure_categories[category] = self.failure_categories.get(category, 0) + 1

    def as_dict(self) -> dict:
        def pct(part: int, whole: int) -> str:
            return f"{(100.0 * part / whole):.1f}%" if whole else "n/a"

        acquired = self.pages_acquired
        return {
            "targets": self.targets,
            "pages_attempted": self.pages_attempted,
            "pages_acquired": acquired,
            "acquisition_success_rate": pct(acquired, self.pages_attempted),
            "pages_failed": self.pages_failed,
            "extraction_attempts": self.extraction_attempts,
            "extraction_succeeded": self.extraction_succeeded,
            "extraction_success_rate": pct(self.extraction_succeeded, self.extraction_attempts),
            "schema_failure_rate": pct(self.schema_failures, self.extraction_attempts),
            "quality_failure_rate": pct(self.quality_failures, self.extraction_attempts),
            "duplicate_rate": pct(self.duplicates, self.extraction_succeeded),
            "landed_in_pending_review": self.pending_review,
            "publication_conversion_rate": pct(self.pending_review, self.extraction_succeeded),
            "named": self.named,
            "nameless_refused": self.nameless,
            "unknown_deadline": self.unknown_deadline,
            "unknown_degree": self.unknown_degree,
            "unknown_funding": self.unknown_funding,
            "records_with_conflicts": self.conflicts,
            "failure_categories": self.failure_categories,
            "rows": self.rows,
        }


def _config(source_id, url: str):
    from services.ingestion.connectors.base_connector import ConnectorConfig

    return ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.3 (+post-M10 controlled expansion; contact: research)",
    )


def _ensure_source(session, url: str) -> SourceRegistry | None:
    """Register the URL as a source if it is not already one.

    `official_url` is unique on `source_registry`, so a source is per page
    rather than per host. That is what the existing registry does, and the
    expansion follows it rather than inventing a second convention.
    """
    existing = (
        session.query(SourceRegistry)
        .filter(SourceRegistry.official_url == url)
        .first()
    )
    if existing is not None:
        return existing
    host = url.split("/")[2]
    try:
        source = SourceRegistry(
            source_name=host,
            official_url=url,
            crawl_entry_url=url,
            crawl_method="http",
            connector_name="GenericHTTPConnector",
            crawl_frequency="manual",
            status="Active",
        )
        session.add(source)
        session.flush()
        return source
    except Exception as exc:  # noqa: BLE001 — an unregistered page is not a blocker
        session.rollback()
        print(f"  SOURCE FAILED {host}: {exc}")
        return None


async def _run(args) -> ExpansionMetrics:
    metrics = ExpansionMetrics(targets=len(TARGETS))
    session = SessionLocal()
    raw_repo = RawDocumentRepository(session)
    raw_mapper = RawDocumentMapper()
    extractor = DeterministicLLMClient()
    acquisition = AcquisitionService(session)

    try:
        for url, label in TARGETS:
            metrics.pages_attempted += 1
            source = _ensure_source(session, url)
            if source is None:
                metrics.pages_failed += 1
                metrics.fail("source registration")
                print(f"  SKIP {url}: could not register source")
                continue

            connector = GenericHTTPConnector(_config(source.source_id, url))
            try:
                fetch = await connector.fetch(url)
                metrics.pages_acquired += 1
            except Exception as exc:  # noqa: BLE001 — a refused fetch is a result
                metrics.pages_failed += 1
                metrics.fail(f"fetch: {type(exc).__name__}")
                print(f"  FETCH FAILED {label}: {type(exc).__name__}")
                continue

            document = raw_mapper.to_orm(fetch)
            existing = raw_repo.get_by_source_and_checksum(
                document.source_id, document.checksum
            )
            document = existing or raw_repo.save(document)

            metrics.extraction_attempts += 1
            result = run_pipeline(str(document.document_id), session, extractor)

            if result.raw_extraction.error:
                metrics.schema_failures += 1
                metrics.fail("schema: " + result.raw_extraction.error[:50])
                print(f"  SCHEMA  {label}: {result.raw_extraction.error[:80]}")
                continue
            if not result.is_valid:
                metrics.quality_failures += 1
                issues = "; ".join(i.message for i in result.validation_report.issues)
                metrics.fail("validation: " + issues[:50])
                print(f"  INVALID {label}: {issues[:100]}")
                continue

            metrics.extraction_succeeded += 1
            scholarship = result.raw_extraction.scholarship
            if scholarship.timeline.application_deadline is None:
                metrics.unknown_deadline += 1
            if scholarship.degree is None:
                metrics.unknown_degree += 1
            if scholarship.funding_type is None:
                metrics.unknown_funding += 1
            if scholarship.scholarship_name:
                metrics.named += 1
            else:
                metrics.nameless += 1

            row = {
                "url": url,
                "label": label,
                "name": scholarship.scholarship_name,
                "provider": scholarship.provider_name,
                "degree": scholarship.degree,
                "funding_type": scholarship.funding_type,
                "deadline": scholarship.timeline.application_deadline,
                "outcome": "dry-run",
            }

            if args.dry_run:
                print(f"  DRY-RUN {label} -> {scholarship.scholarship_name!r}")
                metrics.rows.append(row)
                continue

            saved = acquisition._persist_with_dedup(result, str(document.document_id))
            session.flush()
            if saved is None:
                metrics.duplicates += 1
                row["outcome"] = "duplicate"
                print(f"  DUPLICATE {label}")
            else:
                metrics.pending_review += 1
                row["outcome"] = "pending_review"
                row["id"] = str(saved.scholarship_id)
                blocking = (saved.quality_report or {}).get("blocking")
                row["blocking"] = blocking
                print(
                    f"  PENDING  {label}: {saved.scholarship_name!r}\n"
                    f"           degree={saved.degree!r} funding={saved.funding_type!r} "
                    f"blocking={blocking}"
                )
            metrics.rows.append(row)

        metrics.conflicts = session.execute(
            text(
                "SELECT count(*) FROM scholarship WHERE conflicts IS NOT NULL "
                "AND jsonb_array_length(conflicts) > 0"
            )
        ).scalar()
    finally:
        if not args.dry_run:
            session.commit()
        session.close()

    return metrics


def main() -> None:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", help="write the JSON metrics here")
    args = parser.parse_args()

    metrics = asyncio.run(_run(args))
    print()
    print(json.dumps(metrics.as_dict(), indent=2, ensure_ascii=False))
    if args.report:
        Path(args.report).write_text(
            json.dumps(metrics.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
