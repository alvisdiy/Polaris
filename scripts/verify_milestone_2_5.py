import sys
from services.ingestion.loader import load, LoadInput
from services.ingestion.cleaner import clean
from services.ingestion.extractor import extract
from services.ingestion.validator import validate
from services.ingestion.orchestrator import run_pipeline
from services.ingestion.mock_llm import MockLLMClient, MOCK_SCHOLARSHIP


def verify_milestone_2_5():
    print("--- Starting Ingestion Pipeline (Milestone 2.5) Verification ---")

    # 1. Loader & Cleaner Unit Verification
    print("1. Testing Loader and Cleaner units...")
    raw_html = """
    <html>
        <head><title>MEXT Scholarship Info</title></head>
        <body>
            <header><nav><a href="/">Home</a></nav></header>
            <main>
                <h1>MEXT Scholarship 2027</h1>
                <p>Deadline for application is 2026-05-31.</p>
                <p>This is a government sponsored scholarship for master degrees.</p>
            </main>
            <footer><p>© 2026 Government of Japan</p></footer>
        </body>
    </html>
    """

    doc_input = LoadInput(
        document_id="doc-12345",
        source_id="src-54321",
        source_url="https://www.studyinjapan.go.jp/en/",
        content_type="html",
        raw_content=raw_html,
    )

    loaded = load(doc_input)
    assert loaded.document_id == "doc-12345"
    assert loaded.raw_content == raw_html

    cleaned = clean(loaded)
    print(f"  Cleaned text excerpt: {cleaned.clean_text.strip()[:100]}...")
    # Verify that header/footer navigation has been cleaned by trafilatura
    assert "Home" not in cleaned.clean_text
    assert "Government of Japan" not in cleaned.clean_text
    assert "MEXT Scholarship 2027" in cleaned.clean_text
    print("  [PASS] Cleaner stripped header/footer navigation successfully.")

    # 2. Extractor & MockLLM Unit Verification
    print("2. Testing Extractor with MockLLMClient...")
    mock_client = MockLLMClient()
    extracted = extract(cleaned, mock_client)
    assert extracted.scholarship is not None
    assert extracted.scholarship.scholarship_name == "MEXT Scholarship 2027"
    assert extracted.scholarship.degree == "Master"
    print("  [PASS] Extractor returned correct mock structure.")

    # 3. Validator Unit Verification
    print("3. Testing Validator on valid mock data...")
    report = validate(extracted)
    print(f"  Is Valid: {report.is_valid}")
    for issue in report.issues:
        print(f"    Issue: [{issue.severity}] {issue.field}: {issue.message}")
    assert report.is_valid
    print("  [PASS] Valid data passed validator successfully.")

    # 4. Validator Boundary & Failure Case Verification
    print("4. Testing Validator boundary & failure scenarios...")

    # Case A: Missing Scholarship Name
    bad_data_a = dict(MOCK_SCHOLARSHIP)
    bad_data_a["scholarship_name"] = ""
    client_bad_a = MockLLMClient(bad_data_a)
    extracted_bad_a = extract(cleaned, client_bad_a)
    report_bad_a = validate(extracted_bad_a)
    assert not report_bad_a.is_valid
    assert any(i.field == "scholarship_name" for i in report_bad_a.issues)
    print("  [PASS] Validation caught empty scholarship_name.")

    # Case B: Invalid Scholarship Type Enum
    bad_data_b = dict(MOCK_SCHOLARSHIP)
    bad_data_b["scholarship_type"] = "SuperGovernment"
    client_bad_b = MockLLMClient(bad_data_b)
    extracted_bad_b = extract(cleaned, client_bad_b)
    report_bad_b = validate(extracted_bad_b)
    assert not report_bad_b.is_valid
    assert any(i.field == "scholarship_type" for i in report_bad_b.issues)
    print("  [PASS] Validation caught invalid scholarship_type enum.")

    # Case C: Invalid Date Format
    bad_data_c = dict(MOCK_SCHOLARSHIP)
    bad_data_c["timeline"] = {
        **MOCK_SCHOLARSHIP["timeline"],
        "application_deadline": "May 31st, 2026",
    }
    client_bad_c = MockLLMClient(bad_data_c)
    extracted_bad_c = extract(cleaned, client_bad_c)
    report_bad_c = validate(extracted_bad_c)
    assert not report_bad_c.is_valid
    assert any(i.field == "timeline.application_deadline" for i in report_bad_c.issues)
    print("  [PASS] Validation caught invalid deadline date format.")

    # 5. Orchestrator Integration Verification
    print("5. Testing Orchestrator end-to-end...")
    pipeline_res = run_pipeline(doc_input, mock_client)
    assert pipeline_res.is_valid
    assert pipeline_res.extracted_data is not None
    assert pipeline_res.extracted_data["scholarship_name"] == "MEXT Scholarship 2027"
    assert pipeline_res.extracted_data["eligibility"]["minimum_gpa"] == 3.5
    print("  [PASS] Orchestrator integration executes successfully and returns validated dict.")

    print("\n==========================================")
    print("[SUCCESS] Ingestion Pipeline (Milestone 2.5) Verification Passed!")
    print("==========================================")


if __name__ == "__main__":
    verify_milestone_2_5()
