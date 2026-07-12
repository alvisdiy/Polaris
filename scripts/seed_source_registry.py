import uuid
from database.session import SessionLocal
from database.models.country import Country
from database.models.provider import Provider
from database.models.enums import ProviderType
from database.models.source_registry import SourceRegistry

def seed_data():
    session = SessionLocal()
    try:
        # 1. Countries
        countries_data = [
            {"iso2": "JP", "iso3": "JPN", "name": "Japan"},
            {"iso2": "DE", "iso3": "DEU", "name": "Germany"},
            {"iso2": "GB", "iso3": "GBR", "name": "United Kingdom"},
            {"iso2": "ID", "iso3": "IDN", "name": "Indonesia"},
        ]
        countries = {}
        for c_data in countries_data:
            country = session.query(Country).filter_by(iso3=c_data["iso3"]).first()
            if not country:
                country = Country(
                    iso2=c_data["iso2"],
                    iso3=c_data["iso3"],
                    name=c_data["name"]
                )
                session.add(country)
                session.flush()
            countries[c_data["iso3"]] = country

        # 2. Providers
        providers_data = [
            {
                "provider_code": "MEXT",
                "provider_name": "Ministry of Education, Culture, Sports, Science and Technology",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso3": "JPN",
                "official_url": "https://www.mext.go.jp/en/"
            },
            {
                "provider_code": "DAAD",
                "provider_name": "Deutscher Akademischer Austauschdienst",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso3": "DEU",
                "official_url": "https://www.daad.de/en/"
            },
            {
                "provider_code": "CHEVENING",
                "provider_name": "Foreign, Commonwealth & Development Office",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso3": "GBR",
                "official_url": "https://www.chevening.org/"
            },
            {
                "provider_code": "LPDP",
                "provider_name": "Lembaga Pengelola Dana Pendidikan",
                "provider_type": ProviderType.GOVERNMENT,
                "country_iso3": "IDN",
                "official_url": "https://lpdp.kemenkeu.go.id/"
            },
        ]
        providers = {}
        for p_data in providers_data:
            provider = session.query(Provider).filter_by(provider_code=p_data["provider_code"]).first()
            country = countries[p_data["country_iso3"]]
            if not provider:
                provider = Provider(
                    provider_code=p_data["provider_code"],
                    provider_name=p_data["provider_name"],
                    provider_type=p_data["provider_type"],
                    country_id=country.country_id,
                    official_url=p_data["official_url"]
                )
                session.add(provider)
                session.flush()
            providers[p_data["provider_code"]] = provider

        # 3. Source Registry
        sources_data = [
            {
                "source_name": "Study in Japan",
                "provider_code": "MEXT",
                "country_iso3": "JPN",
                "official_url": "https://www.studyinjapan.go.jp/",
                "crawl_entry_url": "https://www.studyinjapan.go.jp/en/",
                "crawl_method": "Playwright",
                "connector_name": "mext_connector",
                "crawl_frequency": "Monthly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "Active"
            },
            {
                "source_name": "DAAD Scholarship Database",
                "provider_code": "DAAD",
                "country_iso3": "DEU",
                "official_url": "https://www.daad.de/",
                "crawl_entry_url": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                "crawl_method": "Playwright",
                "connector_name": "daad_connector",
                "crawl_frequency": "Monthly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "Active"
            },
            {
                "source_name": "Chevening Scholarships",
                "provider_code": "CHEVENING",
                "country_iso3": "GBR",
                "official_url": "https://www.chevening.org/",
                "crawl_entry_url": "https://www.chevening.org/scholarships/",
                "crawl_method": "Playwright",
                "connector_name": "chevening_connector",
                "crawl_frequency": "Monthly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "Active"
            },
            {
                "source_name": "LPDP Beasiswa",
                "provider_code": "LPDP",
                "country_iso3": "IDN",
                "official_url": "https://lpdp.kemenkeu.go.id/",
                "crawl_entry_url": "https://lpdp.kemenkeu.go.id/en/beasiswa/layanan-beasiswa/",
                "crawl_method": "Playwright",
                "connector_name": "lpdp_connector",
                "crawl_frequency": "Monthly",
                "priority": 1,
                "robots_allowed": True,
                "requires_login": False,
                "status": "Active"
            },
        ]

        for s_data in sources_data:
            source = session.query(SourceRegistry).filter_by(official_url=s_data["official_url"]).first()
            country = countries[s_data["country_iso3"]]
            provider = providers[s_data["provider_code"]]
            if not source:
                source = SourceRegistry(
                    source_name=s_data["source_name"],
                    country_id=country.country_id,
                    provider_id=provider.provider_id,
                    official_url=s_data["official_url"],
                    crawl_entry_url=s_data["crawl_entry_url"],
                    crawl_method=s_data["crawl_method"],
                    connector_name=s_data["connector_name"],
                    crawl_frequency=s_data["crawl_frequency"],
                    priority=s_data["priority"],
                    robots_allowed=s_data["robots_allowed"],
                    requires_login=s_data["requires_login"],
                    status=s_data["status"]
                )
                session.add(source)
                print(f"[SEED] Created SourceRegistry: {s_data['source_name']}")
            else:
                # Update existing record fields to make it truly idempotent
                source.source_name = s_data["source_name"]
                source.country_id = country.country_id
                source.provider_id = provider.provider_id
                source.crawl_entry_url = s_data["crawl_entry_url"]
                source.crawl_method = s_data["crawl_method"]
                source.connector_name = s_data["connector_name"]
                source.crawl_frequency = s_data["crawl_frequency"]
                source.priority = s_data["priority"]
                source.robots_allowed = s_data["robots_allowed"]
                source.requires_login = s_data["requires_login"]
                source.status = s_data["status"]
                print(f"[SEED] Updated existing SourceRegistry: {s_data['source_name']}")

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
