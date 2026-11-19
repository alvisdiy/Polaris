"""CLI for direct scholarship source registration."""

import argparse
import sys

from database.session import SessionLocal
from services.discovery import register_source


def main():
    parser = argparse.ArgumentParser(
        description="Register a known scholarship source (Provider + SourceRegistry)"
    )
    parser.add_argument(
        "--country",
        required=True,
        help="Two-letter country code (e.g., JP, DE, US)",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Official URL of the scholarship source",
    )
    parser.add_argument(
        "--provider-name",
        required=True,
        help="Human-readable name of the publishing organization",
    )
    parser.add_argument(
        "--provider-type",
        required=True,
        choices=["GOVERNMENT", "UNIVERSITY", "FOUNDATION", "NGO", "COMPANY"],
        help="Type of organization",
    )
    parser.add_argument(
        "--crawl-entry-url",
        help="Starting URL for crawling (defaults to official URL)",
    )
    parser.add_argument(
        "--connector",
        default="generic_http",
        help="Connector to use (default: generic_http)",
    )
    parser.add_argument(
        "--source-name",
        help="Source name (defaults to provider_name + ' Scholarship Portal')",
    )

    args = parser.parse_args()

    session = SessionLocal()
    try:
        provider, source = register_source(
            country_iso2=args.country,
            official_url=args.url,
            provider_name=args.provider_name,
            provider_type=args.provider_type,
            session=session,
            crawl_entry_url=args.crawl_entry_url,
            connector_name=args.connector,
            source_name=args.source_name,
        )

        print("✓ Registered source:")
        print(f"  Provider: {provider.provider_name} ({provider.provider_code})")
        print(f"  Source: {source.source_name} ({source.source_id})")
        print(f"  URL: {source.official_url}")
        print(f"  Connector: {source.connector_name}")
        print(f"  Status: {source.status}")

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
