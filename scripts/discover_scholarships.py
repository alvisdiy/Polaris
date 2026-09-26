import argparse
import sys
from database.session import SessionLocal
from services.discovery import discover_scholarships_for_country


def main():
    parser = argparse.ArgumentParser(
        description="Discover scholarship URLs for a country from registered sources"
    )
    parser.add_argument(
        "country",
        help="Two-letter country code (e.g., JP, DE, US)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of URLs to return",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    session = SessionLocal()
    try:
        scholarships = discover_scholarships_for_country(
            country_iso2=args.country,
            session=session,
            limit=args.limit,
        )

        if args.json:
            print(json.dumps(scholarships, indent=2))
        else:
            print(f"Discovered {len(scholarships)} scholarship URLs for {args.country.upper()}:")
            for i, s in enumerate(scholarships, 1):
                print(f"{i:3d}. {s['url']}")
                print(f"     Source: {s['source_name']} ({s['provider_name']})")
                if i >= 20 and not args.limit:  # Limit console output
                    print(f"     ... and {len(scholarships) - 20} more")
                    break

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()