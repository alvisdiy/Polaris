import os
import sys

# Ensure repository root is in sys.path when script is executed directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.discovery import register_source


def seed_data():
    session = SessionLocal()
    try:
        # 1. Countries
        countries_data = [
            {"iso2": "JP", "iso3": "JPN", "name": "Japan"},
            {"iso2": "DE", "iso3": "DEU", "name": "Germany"},
            {"iso2": "GB", "iso3": "GBR", "name": "United Kingdom"},
            {"iso2": "ID", "iso3": "IDN", "name": "Indonesia"},
            {"iso2": "FR", "iso3": "FRA", "name": "France"},
            {"iso2": "US", "iso3": "USA", "name": "United States"},
            {"iso2": "AU", "iso3": "AUS", "name": "Australia"},
            {"iso2": "CN", "iso3": "CHN", "name": "China"},
            {"iso2": "KR", "iso3": "KOR", "name": "South Korea"},
        ]
        countries = {}
        for c_data in countries_data:
            country = session.query(Country).filter_by(iso3=c_data["iso3"]).first()
            if not country:
                country = Country(iso2=c_data["iso2"], iso3=c_data["iso3"], name=c_data["name"])
                session.add(country)
                session.flush()
            countries[c_data["iso3"]] = country

        # 2. Providers (keep for reference, but now created via register_source)
        # We'll create them implicitly through register_source calls below

        # 3. Source Registry - now using register_source for direct registration
        sources_data = [
            {
                "source_name": "Japan Student Services Organization (JASSO)",
                "provider_name": "JASSO",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "JP",
                "official_url": "https://www.jasso.go.jp/en/",
                "crawl_entry_url": "https://www.jasso.go.jp/en/scholarships/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Japan Foundation Scholarship",
                "provider_name": "Japan Foundation",
                "provider_type": ProviderType.FOUNDATION,
                "country_iso2": "JP",
                "official_url": "https://www.jpf.go.jp/e/",
                "crawl_entry_url": "https://www.jpf.go.jp/e/project/japan-foundation-scholarships/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Research Institution Scholarships (RIJ)",
                "provider_name": "Japanese Research Institutes",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "JP",
                "official_url": "https://www.rij.jp/scholarships",
                "crawl_entry_url": "https://www.rij.jp/scholarships",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            # Existing MEXT entry remains below
            {
                "source_name": "Study in Japan (MEXT)",
                "provider_name": "Ministry of Education, Culture, Sports, Science and Technology",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "JP",
                "official_url": "https://www.studyinjapan.go.jp/",
                "crawl_entry_url": "https://www.studyinjapan.go.jp/en/",
                "crawl_method": "html_extraction",
                "connector_name": "mext_connector",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Study in Korea (GKS)",
                "provider_name": "National Institute for International Education",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "KR",
                "official_url": "https://www.studyinkorea.go.kr/",
                "crawl_entry_url": "https://www.studyinkorea.go.kr/en/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "DAAD Scholarship Database",
                "provider_name": "Deutscher Akademischer Austauschdienst",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "DE",
                "official_url": "https://www.daad.de/",
                "crawl_entry_url": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Chevening Scholarships",
                "provider_name": "Foreign, Commonwealth & Development Office",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "GB",
                "official_url": "https://www.chevening.org/",
                "crawl_entry_url": "https://www.chevening.org/scholarships/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "LPDP Beasiswa",
                "provider_name": "Lembaga Pengelola Dana Pendidikan",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "ID",
                "official_url": "https://lpdp.kemenkeu.go.id/",
                "crawl_entry_url": "https://lpdp.kemenkeu.go.id/en/beasiswa/layanan-beasiswa/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Eiffel Scholarship",
                "provider_name": "Campus France",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "FR",
                "official_url": "https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program",
                "crawl_entry_url": "https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Fulbright Foreign Student Program",
                "provider_name": "US Department of State",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "US",
                "official_url": "https://foreign.usaembassy.gov/fulbright/",
                "crawl_entry_url": "https://foreign.usaembassy.gov/fulbright/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Australia Awards",
                "provider_name": "Australian Government",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "AU",
                "official_url": "https://www.australiaawards.gov.au/",
                "crawl_entry_url": "https://www.australiaawards.gov.au/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
            {
                "source_name": "Chinese Government Scholarship",
                "provider_name": "China Scholarship Council",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso2": "CN",
                "official_url": "http://www.csc.edu.cn/laihua/",
                "crawl_entry_url": "http://www.csc.edu.cn/laihua/",
                "crawl_method": "html_extraction",
                "connector_name": "generic_http",
                "crawl_frequency": "weekly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "active",
            },
        ]

        for s_data in sources_data:
            # Check if source already exists (by official_url or crawl_entry_url) to avoid duplicates
            existing_source = session.query(SourceRegistry).filter(
                (SourceRegistry.official_url == s_data["official_url"]) |
                (SourceRegistry.crawl_entry_url == s_data["crawl_entry_url"])
            ).first()
            if existing_source:
                print(f"[SEED] Source already exists: {s_data['source_name']}")
                continue

            provider, source = register_source(
                country_iso2=s_data["country_iso2"],
                official_url=s_data["official_url"],
                provider_name=s_data["provider_name"],
                provider_type=s_data["provider_type"],
                session=session,
                crawl_entry_url=s_data["crawl_entry_url"],
                connector_name=s_data["connector_name"],
                crawl_method=s_data["crawl_method"],
                status=s_data["status"],
                source_name=s_data["source_name"],
            )
            print(f"[SEED] Registered source: {s_data['source_name']} (provider: {provider.provider_name})")


        session.commit()
        print("[SEED SUCCESS] Seeding completed successfully.")

    except Exception as e:
        session.rollback()
        print(f"[SEED FAIL] Seeding failed: {e}")
        raise e
    finally:
        session.close()


if __name__ == "__main__":
    seed_data()
