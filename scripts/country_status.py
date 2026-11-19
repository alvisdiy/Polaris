"""Per-country status: config, last run, frontier, sources, catalogue.

Read-only. This is the first question an operator asks ("what is the state of
country X?") and previously it required four ad-hoc SQL queries.

Usage::

    python scripts/country_status.py
    python scripts/country_status.py JP
    python scripts/country_status.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

from database.models.country import Country
from database.models.discovery_frontier import DiscoveryFrontier
from database.models.exploration_run import ExplorationRun
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.exploration.config_loader import available_countries, load_country_config


def _country_status(session, iso2: str) -> dict:
    country = session.query(Country).filter(Country.iso2 == iso2.upper()).first()
    config = None
    try:
        config = load_country_config(iso2)
    except FileNotFoundError:
        pass

    row = {
        "iso2": iso2.upper(),
        "configured": config is not None,
        "country_row": country is not None,
        "seeds": len(config.seed_urls) if config else 0,
        "soft_tlds": list(config.soft_domain_signals) if config else [],
        "last_run": None,
        "frontier": {},
        "sources": {},
        "catalogue": {},
    }
    if country is None:
        return row

    last_run = (
        session.query(ExplorationRun)
        .filter(ExplorationRun.country_id == country.country_id)
        .order_by(ExplorationRun.started_at.desc())
        .first()
    )
    if last_run is not None:
        row["last_run"] = {
            "status": last_run.status,
            "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
            "candidates": (last_run.metrics or {}).get("candidates_created"),
            "persisted": (last_run.metrics or {}).get("scholarships_persisted"),
        }

    row["frontier"] = {
        state: int(count)
        for state, count in session.query(
            DiscoveryFrontier.state, func.count(DiscoveryFrontier.candidate_id)
        )
        .filter(DiscoveryFrontier.country_id == country.country_id)
        .group_by(DiscoveryFrontier.state)
        .all()
    }
    row["sources"] = {
        state or "unset": int(count)
        for state, count in session.query(
            SourceRegistry.verification_state, func.count(SourceRegistry.source_id)
        )
        .filter(SourceRegistry.country_id == country.country_id)
        .group_by(SourceRegistry.verification_state)
        .all()
    }
    row["catalogue"] = {
        state: int(count)
        for state, count in session.query(
            Scholarship.extraction_status, func.count(Scholarship.scholarship_id)
        )
        .filter(Scholarship.country_id == country.country_id)
        .group_by(Scholarship.extraction_status)
        .all()
    }
    return row


def _print(rows: list[dict]) -> None:
    header = (
        f"{'ISO':4}  {'CFG':3}  {'SEEDS':5}  {'LAST RUN':10}  {'FRONTIER':22}  "
        f"{'SOURCES':22}  {'CATALOGUE':30}"
    )
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        if not row["country_row"]:
            print(f"{row['iso2']:4}  {'yes' if row['configured'] else 'no':3}  "
                  f"{row['seeds']:5}  {'—':10}  {'no country row':22}")
            continue
        last = row["last_run"] or {}
        frontier = ", ".join(f"{k}:{v}" for k, v in sorted(row["frontier"].items())) or "—"
        sources = ", ".join(f"{k}:{v}" for k, v in sorted(row["sources"].items())) or "—"
        catalogue = ", ".join(f"{k}:{v}" for k, v in sorted(row["catalogue"].items())) or "—"
        print(
            f"{row['iso2']:4}  {'yes' if row['configured'] else 'no':3}  "
            f"{row['seeds']:5}  {last.get('status', '—'):10}  {frontier:22}  "
            f"{sources:22}  {catalogue:30}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-country Polaris status")
    parser.add_argument("iso2", nargs="?", help="Country ISO2 (omit for all configured)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    iso2_codes = (
        [args.iso2.upper()] if args.iso2 else [code.upper() for code in available_countries()]
    )

    session = SessionLocal()
    try:
        rows = [_country_status(session, iso2) for iso2 in iso2_codes]
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            _print(rows)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
