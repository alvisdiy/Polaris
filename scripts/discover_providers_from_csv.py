"""Utility to bulk‑import scholarship providers and their official sources from a CSV.

The CSV is the *source of truth* for provider discovery – admins can prepare a list of
all known scholarship‑granting organisations for a country and run this script to
populate the `Provider` and, optionally, a default `SourceRegistry` entry for each.

The script is intentionally simple and uses only the existing DB session and
SQLAlchemy models; no additional third‑party dependencies are introduced.
"""

import csv
import sys
import os

# Ensure project root on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.session import SessionLocal
from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from database.models.enums import ProviderType


def _parse_type(value: str) -> ProviderType:
    """Map a string to :class:`ProviderType` (case‑insensitive)."""
    try:
        return ProviderType[value.upper()]
    except KeyError:
        # Fallback to GOVERNMENT if unknown – the caller should verify correctness.
        return ProviderType.GOVERNMENT


def import_csv(csv_path: str) -> None:
    """Read *csv_path* and upsert providers + optional source entries.

    Expected columns (header row required)::

        country_iso2,provider_code,provider_name,provider_type,official_url,
        source_name,source_url

    * ``source_name`` and ``source_url`` are optional – if omitted no SourceRegistry
      record is created.
    """
    session = SessionLocal()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                iso2 = row["country_iso2"].strip().upper()
                # Resolve / create Country
                country = session.query(Country).filter_by(iso2=iso2).first()
                if not country:
                    raise ValueError(f"Country with iso2={iso2} not found – seed it first.")

                # Upsert Provider
                provider = (
                    session.query(Provider)
                    .filter_by(provider_code=row["provider_code"].strip())
                    .first()
                )
                if not provider:
                    provider = Provider(
                        provider_code=row["provider_code"].strip(),
                        provider_name=row["provider_name"].strip(),
                        provider_type=_parse_type(row["provider_type"].strip()),
                        country_id=country.country_id,
                        official_url=row["official_url"].strip(),
                    )
                    session.add(provider)
                    session.flush()  # assign provider_id
                    print(f"[IMPORT] Created Provider {provider.provider_code}")
                else:
                    # Update mutable fields for idempotency
                    provider.provider_name = row["provider_name"].strip()
                    provider.provider_type = _parse_type(row["provider_type"].strip())
                    provider.official_url = row["official_url"].strip()
                    provider.country_id = country.country_id
                    print(f"[IMPORT] Updated Provider {provider.provider_code}")

                # Optional SourceRegistry entry
                source_name = row.get("source_name", "").strip()
                source_url = row.get("source_url", "").strip()
                if source_name and source_url:
                    source = (
                        session.query(SourceRegistry)
                        .filter_by(official_url=source_url)
                        .first()
                    )
                    if not source:
                        source = SourceRegistry(
                            source_name=source_name,
                            country_id=country.country_id,
                            provider_id=provider.provider_id,
                            official_url=source_url,
                            crawl_entry_url=source_url,  # default to same URL
                            crawl_method="Playwright",
                            connector_name="generic_playwright",
                            crawl_frequency="Monthly",
                            priority=1,
                            robots_allowed=True,
                            requires_login=False,
                            status="Active",
                        )
                        session.add(source)
                        print(f"[IMPORT] Created Source {source_name} for {provider.provider_code}")
                    else:
                        # Update mutable fields (idempotent)
                        source.source_name = source_name
                        source.country_id = country.country_id
                        source.provider_id = provider.provider_id
                        source.crawl_entry_url = source_url
                        source.crawl_method = "Playwright"
                        source.connector_name = "generic_playwright"
                        source.crawl_frequency = "Monthly"
                        source.priority = 1
                        source.robots_allowed = True
                        source.requires_login = False
                        source.status = "Active"
                        print(f"[IMPORT] Updated Source {source_name}")
        session.commit()
        print("[IMPORT] CSV import completed successfully.")
    except Exception as e:
        session.rollback()
        print(f"[IMPORT] Failed: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/discover_providers_from_csv.py <path/to/providers.csv>")
        sys.exit(1)
    import_csv(sys.argv[1])
