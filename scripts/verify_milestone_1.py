from database.session import SessionLocal
from database.models.country import Country
from database.models.provider import Provider
from database.models.university import University
from database.models.enums import ProviderType


def run_validation():
    session = SessionLocal()
    # Clean up existing test records if any
    try:
        session.query(University).filter(University.university_code.like("TEST-%")).delete(synchronize_session=False)
        session.query(Provider).filter(Provider.provider_code.like("TEST-%")).delete(synchronize_session=False)
        session.query(Country).filter(Country.iso3.like("TS%")).delete(synchronize_session=False)
        session.commit()
    except Exception as e:
        session.rollback()

    try:
        print("1. Inserting country (Test Country)...")
        test_country = Country(iso2="TS", iso3="TSA", name="Test Country")
        session.add(test_country)
        session.flush()

        print("2. Inserting provider (Test Provider)...")
        test_provider = Provider(
            provider_code="TEST-PROV",
            provider_name="Test Provider Org",
            provider_type=ProviderType.GOVERNMENT,
            country_id=test_country.country_id,
            official_url="https://test.prov.org"
        )
        session.add(test_provider)
        session.flush()

        print("3. Inserting university (Test University)...")
        test_uni = University(
            university_code="TEST-UNI",
            name="Test University Org",
            country_id=test_country.country_id,
            official_url="https://test.uni.edu"
        )
        session.add(test_uni)
        session.flush()

        session.commit()
        print("[SUCCESS] Insert and commit successful!")

        # Query and verify
        print("\n--- Verifying relationships ---")
        q_country = session.query(Country).filter_by(iso3="TSA").one()
        print(f"Queried Country: {q_country.name} ({q_country.country_id})")
        print(f"Country.providers: {[p.provider_code for p in q_country.providers]}")
        print(f"Country.universities: {[u.university_code for u in q_country.universities]}")

        assert len(q_country.providers) == 1
        assert q_country.providers[0].provider_code == "TEST-PROV"
        assert len(q_country.universities) == 1
        assert q_country.universities[0].university_code == "TEST-UNI"
        print("[SUCCESS] Country -> Providers & Universities relationship verification passed!")

        q_prov = session.query(Provider).filter_by(provider_code="TEST-PROV").one()
        print(f"Queried Provider: {q_prov.provider_name} ({q_prov.provider_id})")
        print(f"Provider.country: {q_prov.country.name if q_prov.country else 'None'}")
        assert q_prov.country is not None
        assert q_prov.country.iso3 == "TSA"
        print("[SUCCESS] Provider -> Country relationship verification passed!")

        q_uni = session.query(University).filter_by(university_code="TEST-UNI").one()
        print(f"Queried University: {q_uni.name} ({q_uni.university_id})")
        print(f"University.country: {q_uni.country.name}")
        assert q_uni.country.iso3 == "TSA"
        print("[SUCCESS] University -> Country relationship verification passed!")

        # Clean up
        print("\n--- Cleaning up data (confirming integrity) ---")
        session.delete(q_uni)
        session.delete(q_prov)
        session.delete(q_country)
        session.commit()
        print("[SUCCESS] Cleanup complete. DB is clean.")

    except Exception as e:
        session.rollback()
        print(f"[FAIL] Validation failed: {e}")
        raise e
    finally:
        session.close()


if __name__ == "__main__":
    run_validation()
