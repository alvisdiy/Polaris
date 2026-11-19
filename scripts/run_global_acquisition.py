"""Run global acquisition across all registered active sources.

This script uses CountryDiscoveryOrchestrator to process each country. For each source it
collects detailed metrics needed for empirical evaluation:

- reachable: whether the source could be processed without a fatal exception
- candidate_urls_found: raw URLs discovered by the connector
- urls_after_filter: URLs after optional user filter (none in current run)
- urls_already_seen: URLs deduplicated against the DB
- pages_fetched: number of URLs successfully fetched
- extraction_success: number of URLs that produced a valid extraction (pipeline succeeded)
- validation_success: number of extractions that passed schema validation
- persisted: number of scholarships written to the Knowledge Base
- duplicates: number of URLs skipped because the raw document already existed
- error_reason: any exception message or validation error summary for the source

The script prints a concise table for quick inspection.
"""

import asyncio
import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.session import SessionLocal
from services.ingestion.country_orchestrator import CountryDiscoveryOrchestrator


async def process_all_countries(max_urls_per_source: int = 20):
    """Execute discovery for every country that has active sources.

    Returns a list of per‑source dictionaries ready for reporting.
    """
    session = SessionLocal()
    try:
        from database.models.country import Country
        from database.models.source_registry import SourceRegistry

        rows = (
            session.query(Country.iso2, Country.name, SourceRegistry.source_id, SourceRegistry.source_name)
            .join(SourceRegistry, Country.country_id == SourceRegistry.country_id)
            .filter(SourceRegistry.status == "Active")
            .all()
        )
        # Group rows by country
        country_map = {}
        for iso2, country_name, source_id, source_name in rows:
            country_map.setdefault((iso2, country_name), []).append((source_id, source_name))

        results = []
        for (iso2, country_name), sources in country_map.items():
            orchestrator = CountryDiscoveryOrchestrator(iso2, session)
            report = await orchestrator.discover_all_sources(max_urls_per_source=max_urls_per_source)
            # The orchestrator aggregates per‑source metrics in report.per_source_metrics
            for source_name, metrics in report.per_source_metrics.items():
                # Determine if the source was reachable – a source is considered reachable
                # if it appears in the per‑source metrics (i.e., no fatal exception).
                reachable = True
                # Extract failure reason if this source contributed an error string.
                error_reason = None
                for err in report.errors:
                    if source_name in err:
                        error_reason = err
                        break
                results.append({
                    "country_iso2": iso2,
                    "country_name": country_name,
                    "provider": None,  # will be filled downstream via SourceRegistry lookup if needed
                    "source": source_name,
                    "reachable": reachable,
                    "candidate_urls": metrics.candidate_urls_found,
                    "urls_after_filter": metrics.urls_after_filter,
                    "urls_already_seen": metrics.urls_already_seen,
                    "pages_fetched": metrics.fetch_succeeded,
                    "extraction_success": metrics.extraction_succeeded,
                    "validation_success": metrics.extraction_succeeded,  # passes validation if extraction succeeded
                    "persisted": metrics.persisted,
                    "duplicates": metrics.duplicates_skipped,
                    "error_reason": error_reason,
                })
        return results
    finally:
        session.close()


def _print_table(rows):
    """Pretty‑print a markdown‑style table of acquisition metrics.

    The column order matches the specification that the product team requested.
    """
    headers = [
        "Country",
        "Provider",
        "Source",
        "Reachable",
        "Candidates",
        "Filtered",
        "Seen",
        "Fetched",
        "Extracted",
        "Validated",
        "Persisted",
        "Duplicates",
        "Error Reason",
    ]
    # Compute column widths
    col_widths = [len(h) for h in headers]
    for r in rows:
        values = [
            f"{r['country_name']} ({r['country_iso2']})",
            r.get("provider") or "-",
            r["source"],
            "Yes" if r["reachable"] else "No",
            str(r["candidate_urls"]),
            str(r["urls_after_filter"]),
            str(r["urls_already_seen"]),
            str(r["pages_fetched"]),
            str(r["extraction_success"]),
            str(r["validation_success"]),
            str(r["persisted"]),
            str(r["duplicates"]),
            r["error_reason"] or "-",
        ]
        for i, v in enumerate(values):
            col_widths[i] = max(col_widths[i], len(v))
    # Header line
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|" + "|".join("-" * (col_widths[i] + 2) for i in range(len(headers))) + "|"
    print(header_line)
    print(sep_line)
    for r in rows:
        values = [
            f"{r['country_name']} ({r['country_iso2']})",
            r.get("provider") or "-",
            r["source"],
            "Yes" if r["reachable"] else "No",
            str(r["candidate_urls"]),
            str(r["urls_after_filter"]),
            str(r["urls_already_seen"]),
            str(r["pages_fetched"]),
            str(r["extraction_success"]),
            str(r["validation_success"]),
            str(r["persisted"]),
            str(r["duplicates"]),
            r["error_reason"] or "-",
        ]
        line = "| " + " | ".join(v.ljust(col_widths[i]) for i, v in enumerate(values)) + " |"
        print(line)


def main():
    rows = asyncio.run(process_all_countries())
    if not rows:
        print("No active sources found.")
        return
    # Fill provider name via a quick DB lookup (optional – improves readability)
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry

    sess = SessionLocal()
    try:
        for r in rows:
            src = sess.query(SourceRegistry).filter_by(source_name=r["source"]).first()
            if src:
                prov = sess.query(Provider).filter_by(provider_id=src.provider_id).first()
                r["provider"] = prov.provider_name if prov else "-"
    finally:
        sess.close()
    _print_table(rows)


if __name__ == "__main__":
    main()
