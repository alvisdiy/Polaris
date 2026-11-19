"""Read-only inspection of live provider / scholarship linkage (Phase 7.3).

Answers one question with evidence rather than assumption: has
``ProviderResolver._merge_domain_duplicates`` — which bulk-updates
``scholarship.provider_id`` — ever re-pointed an APPROVED record in the shared
development database? Nothing is written.
"""

from __future__ import annotations

from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import func

from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.exploration.url_utils import domain_of, registered_domain


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    try:
        providers = session.query(Provider).all()
        merged = [p for p in providers if p.merged_into_provider_id]
        print(f"providers                       : {len(providers)}")
        print(f"providers marked as merged      : {len(merged)}")

        # Scholarships that point at a provider which was later merged away.
        merged_ids = [p.provider_id for p in merged]
        affected = (
            session.query(Scholarship.provider_id, func.count(Scholarship.scholarship_id))
            .filter(Scholarship.provider_id.in_(merged_ids))
            .group_by(Scholarship.provider_id)
            .all()
            if merged_ids
            else []
        )
        total_affected = sum(count for _, count in affected)
        print(f"scholarships still on a merged  : {total_affected}")

        statuses = Counter()
        if merged_ids:
            for status, count in (
                session.query(Scholarship.extraction_status, func.count())
                .filter(Scholarship.provider_id.in_(merged_ids))
                .group_by(Scholarship.extraction_status)
                .all()
            ):
                statuses[status] = count
        print(f"  by status                     : {dict(statuses)}")

        # Approved records grouped by the provider they currently point at.
        approved = (
            session.query(Scholarship, Provider)
            .join(Provider, Scholarship.provider_id == Provider.provider_id)
            .filter(Scholarship.extraction_status == "approved")
            .all()
        )
        print(f"\napproved scholarships           : {len(approved)}")
        by_domain: dict[str, set[str]] = {}
        for scholarship, provider in approved:
            domain = registered_domain(domain_of(provider.official_url or ""))
            by_domain.setdefault(domain or "(none)", set()).add(provider.provider_name)
        multi = {d: names for d, names in by_domain.items() if len(names) > 1}
        print(f"domains hosting >1 approved provider name: {len(multi)}")
        for domain, names in sorted(multi.items())[:10]:
            print(f"  {domain}: {sorted(names)}")

        sources_per_provider = (
            session.query(SourceRegistry.provider_id, func.count())
            .group_by(SourceRegistry.provider_id)
            .all()
        )
        print(f"\nsources linked to providers     : {len(sources_per_provider)}")

        unlinked = (
            session.query(func.count())
            .select_from(Scholarship)
            .filter(Scholarship.provider_id.is_(None))
            .scalar()
        )
        print(f"scholarships with no provider   : {unlinked}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
