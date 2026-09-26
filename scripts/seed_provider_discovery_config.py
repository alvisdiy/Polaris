"""Seed provider discovery configurations for countries."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models.country import Country
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.session import SessionLocal


def seed_configs():
    session = SessionLocal()
    try:
        # Discovery configurations per country
        # Each config represents a discovery surface (portal/directory) to crawl for providers
        configs_data = [
            {
                "country_iso2": "JP",
                "discovery_surface_url": "https://www.jasso.go.jp/en/",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".go.jp", ".ac.jp", ".or.jp"],
                "keyword_filters": [
                    "scholarship",
                    "fellowship",
                    "grant",
                    "award",
                    "stipend",
                    "bourse",
                    "奨学金",
                    "장학금",
                    "Stipendium",
                    "subsidy",
                    "research",
                    "financial-support",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "JP",
                "discovery_surface_url": "https://www.mext.go.jp/en/",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".go.jp", ".ac.jp", ".or.jp"],
                "keyword_filters": [
                    "scholarship",
                    "grant",
                    "fellowship",
                    "award",
                    "stipend",
                    "bourse",
                    "奨学金",
                    "장학금",
                    "Stipendium",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 2,
                "is_active": True,
            },
            {
                "country_iso2": "DE",
                "discovery_surface_url": "https://www.daad.de/en/",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".de"],
                "keyword_filters": [
                    "scholarship",
                    "stipendium",
                    "förderung",
                    "award",
                    "bourse",
                    "grant",
                    "奨学金",
                    "장학금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "GB",
                "discovery_surface_url": "https://www.chevening.org/",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".gov.uk", ".ac.uk", ".org.uk"],
                "keyword_filters": [
                    "scholarship",
                    "award",
                    "grant",
                    "funding",
                    "bourse",
                    "奨学金",
                    "장학금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "US",
                "discovery_surface_url": "https://en.wikipedia.org/wiki/List_of_colleges_and_universities_in_the_United_States",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".gov", ".edu"],
                "keyword_filters": [
                    "scholarship",
                    "grant",
                    "fellowship",
                    "award",
                    "bourse",
                    "奨学金",
                    "장학금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "KR",
                "discovery_surface_url": "https://en.wikipedia.org/wiki/List_of_universities_in_South_Korea",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".go.kr", ".ac.kr", ".kr"],
                "keyword_filters": [
                    "scholarship",
                    "gks",
                    "grant",
                    "fellowship",
                    "award",
                    "bourse",
                    "장학금",
                    "奨学金",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "ID",
                "discovery_surface_url": "https://en.wikipedia.org/wiki/List_of_universities_in_Indonesia",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".go.id", ".ac.id", ".id"],
                "keyword_filters": [
                    "beasiswa",
                    "scholarship",
                    "grant",
                    "fellowship",
                    "award",
                    "bourse",
                    "lpdp",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "FR",
                "discovery_surface_url": "https://www.campusfrance.org/en",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".gouv.fr", ".fr"],
                "keyword_filters": [
                    "scholarship",
                    "bourse",
                    "grant",
                    "fellowship",
                    "award",
                    "funding",
                    "stipendium",
                    "奨学金",
                    "장학금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "AU",
                "discovery_surface_url": "https://www.studyinaustralia.gov.au/",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".gov.au", ".edu.au", ".au"],
                "keyword_filters": [
                    "scholarship",
                    "grant",
                    "fellowship",
                    "award",
                    "bourse",
                    "funding",
                    "奨学金",
                    "장학금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
            {
                "country_iso2": "CN",
                "discovery_surface_url": "https://en.wikipedia.org/wiki/List_of_universities_in_China",
                "discovery_strategy": "link_discovery",
                "allowed_tlds": [".cn", ".edu.cn"],
                "keyword_filters": [
                    "scholarship",
                    "csc",
                    "grant",
                    "fellowship",
                    "award",
                    "bourse",
                    "奨学金",
                    "장学금",
                ],
                "auto_verify_enabled": True,
                "confidence_threshold": 0.6,
                "priority": 1,
                "is_active": True,
            },
        ]

        for cfg_data in configs_data:
            country = session.query(Country).filter_by(iso2=cfg_data["country_iso2"]).first()
            if not country:
                print(f"[WARN] Country {cfg_data['country_iso2']} not found, skipping")
                continue

            # Check if config already exists (idempotent)
            existing = (
                session.query(ProviderDiscoveryConfig)
                .filter_by(
                    country_id=country.country_id,
                    discovery_surface_url=cfg_data["discovery_surface_url"],
                )
                .first()
            )

            if not existing:
                config = ProviderDiscoveryConfig(
                    country_id=country.country_id,
                    discovery_surface_url=cfg_data["discovery_surface_url"],
                    discovery_strategy=cfg_data["discovery_strategy"],
                    allowed_tlds=cfg_data["allowed_tlds"],
                    keyword_filters=cfg_data["keyword_filters"],
                    auto_verify_enabled=cfg_data["auto_verify_enabled"],
                    confidence_threshold=cfg_data["confidence_threshold"],
                    priority=cfg_data["priority"],
                    is_active=cfg_data["is_active"],
                )
                session.add(config)
                print(f"[SEED] Created ProviderDiscoveryConfig for {country.iso2}: {cfg_data['discovery_surface_url']}")
            else:
                # Update existing to ensure consistency
                existing.allowed_tlds = cfg_data["allowed_tlds"]
                existing.keyword_filters = cfg_data["keyword_filters"]
                existing.auto_verify_enabled = cfg_data["auto_verify_enabled"]
                existing.confidence_threshold = cfg_data["confidence_threshold"]
                existing.priority = cfg_data["priority"]
                existing.is_active = cfg_data["is_active"]
                print(f"[SEED] Updated existing ProviderDiscoveryConfig for {country.iso2}: {cfg_data['discovery_surface_url']}")

        session.commit()
        print("[SEED SUCCESS] Provider discovery configs seeded successfully.")

    except Exception as e:
        session.rollback()
        print(f"[SEED FAIL] Seeding failed: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_configs()
