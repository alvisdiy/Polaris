"""Seed provider-discovery configurations for the configured countries.

Each row is an authoritative page that lists organizations, plus the type of
organization it lists. The provider-discovery specification calls these
surfaces ``government_portal``, ``education_directory``, ``scholarship_agency``
and ``university_directory``; here the type is the ``organization_type`` column
that the strategy factory reads.

Run after countries exist::

    python scripts/seed_provider_discovery_config.py

Idempotent: an existing row for the same country + surface is updated in place.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models.country import Country
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.session import SessionLocal
from services.exploration.config_loader import load_country_config

#: (ISO2, discovery surface, organization type, priority)
#:
#: Only official portals. The previous list used Wikipedia "List of
#: universities" pages for US/KR/ID/CN, which the data-acquisition strategy
#: explicitly treats as reference-only, never as an official source.
DISCOVERY_SURFACES: tuple[tuple[str, str, str, int], ...] = (
    # Japan — government + national agencies
    ("JP", "https://www.mext.go.jp/en/", "Government", 1),
    ("JP", "https://www.jasso.go.jp/en/", "Scholarship Agency", 1),
    ("JP", "https://www.studyinjapan.go.jp/en/", "Government", 2),
    ("JP", "https://www.jsps.go.jp/english/", "Scholarship Agency", 2),
    # Germany
    ("DE", "https://www.daad.de/en/", "Scholarship Agency", 1),
    ("DE", "https://www.bmbf.de/en/", "Government", 1),
    ("DE", "https://www.research-in-germany.org/en/", "Government", 2),
    # United Kingdom
    ("GB", "https://www.chevening.org/", "Government", 1),
    ("GB", "https://www.britishcouncil.org/", "Scholarship Agency", 2),
    ("GB", "https://www.ukcisa.org.uk/", "Scholarship Agency", 2),
    # United States
    ("US", "https://educationusa.state.gov/", "Government", 1),
    ("US", "https://foreign.fulbrightonline.org/", "Scholarship Agency", 1),
    # South Korea
    ("KR", "https://www.studyinkorea.go.kr/en/main.do", "Government", 1),
    ("KR", "https://www.gks.go.kr/", "Government", 1),
    # Indonesia
    ("ID", "https://lpdp.kemenkeu.go.id/", "Government", 1),
    ("ID", "https://beasiswa.kemdikbud.go.id/", "Government", 1),
    # France
    ("FR", "https://www.campusfrance.org/en", "Government", 1),
    ("FR", "https://www.enseignementsup-recherche.gouv.fr/en", "Government", 2),
    # Australia
    ("AU", "https://www.studyaustralia.gov.au/en/scholarships", "Government", 1),
    ("AU", "https://www.dfat.gov.au/people-to-people/australia-awards", "Government", 1),
    # China
    ("CN", "https://www.campuschina.org/", "Government", 1),
    ("CN", "https://www.csc.edu.cn/", "Government", 1),
)

#: Kept for the config schema; link discovery filters by TLD and domain, not by
#: keyword. A surface lists organizations, not funding pages, so a keyword
#: filter would drop the organizations themselves.
KEYWORD_FILTERS = (
    "scholarship",
    "fellowship",
    "grant",
    "award",
    "beasiswa",
    "stipendium",
    "奨学金",
    "장학금",
)


def seed_configs() -> None:
    session = SessionLocal()
    created = updated = skipped = 0
    try:
        for iso2, surface_url, organization_type, priority in DISCOVERY_SURFACES:
            country = session.query(Country).filter_by(iso2=iso2).first()
            if not country:
                print(f"[WARN] Country {iso2} not found, skipping {surface_url}")
                skipped += 1
                continue

            try:
                allowed_tlds = list(load_country_config(iso2).soft_domain_signals)
            except FileNotFoundError:
                print(f"[WARN] No country config for {iso2}, skipping {surface_url}")
                skipped += 1
                continue

            existing = (
                session.query(ProviderDiscoveryConfig)
                .filter_by(country_id=country.country_id, discovery_surface_url=surface_url)
                .first()
            )

            if existing:
                existing.organization_type = organization_type
                existing.discovery_strategy = "link_discovery"
                existing.allowed_tlds = allowed_tlds
                existing.keyword_filters = list(KEYWORD_FILTERS)
                existing.auto_verify_enabled = True
                existing.confidence_threshold = 0.6
                existing.priority = priority
                existing.is_active = True
                updated += 1
                print(f"[SEED] Updated {iso2} {organization_type}: {surface_url}")
            else:
                session.add(
                    ProviderDiscoveryConfig(
                        country_id=country.country_id,
                        organization_type=organization_type,
                        discovery_surface_url=surface_url,
                        discovery_strategy="link_discovery",
                        allowed_tlds=allowed_tlds,
                        keyword_filters=list(KEYWORD_FILTERS),
                        auto_verify_enabled=True,
                        confidence_threshold=0.6,
                        priority=priority,
                        is_active=True,
                    )
                )
                created += 1
                print(f"[SEED] Created {iso2} {organization_type}: {surface_url}")

        session.commit()
        print(
            f"[SEED SUCCESS] Provider discovery configs: "
            f"{created} created, {updated} updated, {skipped} skipped."
        )
    except Exception as exc:
        session.rollback()
        print(f"[SEED FAIL] {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_configs()
