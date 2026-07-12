"""Verify Milestone 2.9 — Scholarship Persistence.

End-to-end verification:
1. Read SourceRegistry record
2. Execute connector (fetch page)
3. Persist RawDocument
4. Execute Loader → Cleaner → MockLLM → Validator
5. Persist Scholarship via mapper + repository
6. Read Scholarship back and assert fields match
"""

import asyncio
import sys

from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.provider import Provider
from database.models.country import Country
from services.ingestion.connectors import ConnectorConfig, MEXTConnector
from services.ingestion.repositories import RawDocumentMapper, RawDocumentRepository
from services.ingestion.orchestrator import run_pipeline, persist_scholarship
from services.ingestion.mock_llm import MockLLMClient
from services.scholarship import ScholarshipRepository


async def run_verification():
    print("--- Starting Milestone 2.9 (Scholarship Persistence) Verification ---")

    session = SessionLocal()
    doc_id = None
    scholarship_id = None

    try:
        # 1. Fetch source registry config
        print("1. Reading SourceRegistry entry...")
        source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
        if not source:
            print("[FAIL] 'Study in Japan' not found in SourceRegistry. Run seed script first.")
            print("FAIL")
            sys.exit(1)
        print(f"   Source: {source.source_name} ({source.source_id})")

        # 2. Run connector to fetch page
        print("2. Fetching page with MEXTConnector...")
        config = ConnectorConfig(
            source_id=source.source_id,
            url=source.crawl_entry_url,
            timeout=30,
            user_agent="Polaris/0.1 Milestone 2.9 Verification",
        )
        connector = MEXTConnector(config)
        await connector.connect()
        try:
            result = await connector.fetch()
            print("   Fetch completed.")
        except Exception as e:
            print(f"[FAIL] Fetch failed: {e}")
            await connector.close()
            print("FAIL")
            sys.exit(1)
        finally:
            await connector.close()

        # 3. Persist RawDocument
        print("3. Persisting RawDocument...")
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(result)

        repo = RawDocumentRepository(session)
        saved_doc = repo.save(raw_doc)
        doc_id = saved_doc.document_id
        print(f"   RawDocument persisted with ID: {doc_id}")

        # 4. Execute pipeline (Loader → Cleaner → MockLLM → Validator)
        print("4. Executing orchestrator processing pipeline...")
        llm_client = MockLLMClient()
        pipeline_res = run_pipeline(str(doc_id), session, llm_client)

        print(f"   Pipeline is_valid: {pipeline_res.is_valid}")
        if not pipeline_res.is_valid:
            print(f"[FAIL] Pipeline validation failed: {pipeline_res.validation_report.issues}")
            print("FAIL")
            sys.exit(1)

        # 5. Persist Scholarship
        print("5. Persisting Scholarship via mapper + repository...")
        scholarship = persist_scholarship(pipeline_res, str(doc_id), session)
        if scholarship is None:
            print("[FAIL] persist_scholarship returned None despite valid pipeline result.")
            print("FAIL")
            sys.exit(1)
        scholarship_id = scholarship.scholarship_id
        print(f"   Scholarship persisted with ID: {scholarship_id}")

        # 6. Read Scholarship back and assert
        print("6. Reading Scholarship back from repository...")
        sch_repo = ScholarshipRepository(session)
        loaded_scholarship = sch_repo.get_by_id(scholarship_id)
        if loaded_scholarship is None:
            print("[FAIL] Scholarship not found after save.")
            print("FAIL")
            sys.exit(1)

        # Resolve expected reference entities
        expected_provider = session.query(Provider).filter_by(
            provider_name="Ministry of Education, Culture, Sports, Science and Technology"
        ).first()
        expected_country = session.query(Country).filter_by(name="Japan").first()

        print("\n--- Validating Scholarship Fields ---")

        # Assert scholarship_name
        expected_name = "MEXT Scholarship 2027"
        assert loaded_scholarship.scholarship_name == expected_name, (
            f"scholarship_name mismatch: '{loaded_scholarship.scholarship_name}' != '{expected_name}'"
        )
        print(f"  [PASS] scholarship_name = {loaded_scholarship.scholarship_name}")

        # Assert provider
        assert loaded_scholarship.provider_id == expected_provider.provider_id, (
            f"provider_id mismatch: {loaded_scholarship.provider_id} != {expected_provider.provider_id}"
        )
        print(f"  [PASS] provider matches ({expected_provider.provider_name})")

        # Assert country
        assert loaded_scholarship.country_id == expected_country.country_id, (
            f"country_id mismatch: {loaded_scholarship.country_id} != {expected_country.country_id}"
        )
        print(f"  [PASS] country matches ({expected_country.name})")

        # Assert degree
        expected_degree = "Master"
        assert loaded_scholarship.degree == expected_degree, (
            f"degree mismatch: '{loaded_scholarship.degree}' != '{expected_degree}'"
        )
        print(f"  [PASS] degree = {loaded_scholarship.degree}")

        # Assert deadline
        from datetime import date
        expected_deadline = date(2026, 5, 31)
        assert loaded_scholarship.application_deadline == expected_deadline, (
            f"application_deadline mismatch: {loaded_scholarship.application_deadline} != {expected_deadline}"
        )
        print(f"  [PASS] application_deadline = {loaded_scholarship.application_deadline}")

        # Assert extraction_status
        assert loaded_scholarship.extraction_status == "pending_review", (
            f"extraction_status mismatch: '{loaded_scholarship.extraction_status}' != 'pending_review'"
        )
        print(f"  [PASS] extraction_status = {loaded_scholarship.extraction_status}")

        # Assert repository returns the same entity
        assert loaded_scholarship.scholarship_id == scholarship_id, (
            "Repository returned different entity than saved."
        )
        print("  [PASS] repository returns the same entity")

        # Assert find_duplicate works
        duplicate = sch_repo.find_duplicate(
            scholarship_name=loaded_scholarship.scholarship_name,
            provider_id=loaded_scholarship.provider_id,
            application_cycle=loaded_scholarship.application_cycle,
            source_id=loaded_scholarship.source_id,
        )
        assert duplicate is not None, "find_duplicate returned None for existing scholarship"
        assert duplicate.scholarship_id == scholarship_id, "find_duplicate returned wrong entity"
        print("  [PASS] find_duplicate detects existing scholarship")

        # Assert ORM relationships load
        _ = loaded_scholarship.provider
        _ = loaded_scholarship.country
        _ = loaded_scholarship.source
        print("  [PASS] ORM relationships load correctly")

        # Cleanup test records
        print("\n7. Cleaning up test records...")
        session.query(Scholarship).filter_by(scholarship_id=scholarship_id).delete()
        session.query(RawDocument).filter_by(document_id=doc_id).delete()
        session.commit()
        print("   Cleaned up test records.")

        print("\n==========================================")
        print("PASS")
        print("==========================================")

    except AssertionError as e:
        # Cleanup even on failure
        if scholarship_id:
            session.query(Scholarship).filter_by(scholarship_id=scholarship_id).delete()
        if doc_id:
            session.query(RawDocument).filter_by(document_id=doc_id).delete()
        session.commit()
        print(f"\n[FAIL] Assertion failed: {e}")
        print("FAIL")
        sys.exit(1)
    except Exception as e:
        # Cleanup on unexpected error
        if scholarship_id:
            session.query(Scholarship).filter_by(scholarship_id=scholarship_id).delete()
        if doc_id:
            session.query(RawDocument).filter_by(document_id=doc_id).delete()
        session.commit()
        print(f"\n[FAIL] Unexpected error: {e}")
        print("FAIL")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(run_verification())
