from services.ingestion.cleaner import AnchorLink, CleanedDocument
from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship
from services.ingestion.orchestrator import _invoke_client
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.validator import validate


def test_extractor_selects_only_explicitly_labelled_external_targets():
    article_url = "https://www.opportunitiescircle.com/sample-scholarship/"
    extracted = DeterministicLLMClient().extract_scholarship(
        "This scholarship supports international applicants.",
        article_url,
        anchor_links=(
            {"text": "Official Site", "href": "https://official.example/program"},
            {"text": "Apply Now", "href": "https://apply.example/form"},
            {"text": "More Scholarship Articles", "href": article_url + "related/"},
            {"text": "Official guidance", "href": "https://www.opportunitiescircle.com/guide/"},
        ),
    )

    assert extracted["official_source"] == "https://official.example/program"
    assert extracted["application_url"] == "https://apply.example/form"
    assert extracted["_extraction"]["source_url"] == article_url
    assert article_url not in {
        extracted["official_source"],
        extracted["application_url"],
    }
    assert extracted["_extraction"]["outbound_links"] == [
        {"text": "Official Site", "url": "https://official.example/program"},
        {"text": "Apply Now", "url": "https://apply.example/form"},
    ]


def test_extractor_does_not_use_article_url_as_missing_target_fallback():
    article_url = "https://fullyscholarships.com/eiffel-excellence-scholarship-2027/"
    extracted = DeterministicLLMClient().extract_scholarship(
        "Eiffel Excellence Scholarship 2027 applications close soon.",
        article_url,
        anchor_links=({"text": "Read more", "href": "/related-scholarship/"},),
    )

    assert extracted["official_source"] is None
    assert extracted["application_url"] is None
    assert extracted["_extraction"]["source_url"] == article_url


def test_aggregator_can_resolve_program_link_with_provider_name_anchor():
    article_url = "https://fullyscholarships.com/eiffel-excellence-scholarship-2027/"
    extracted = DeterministicLLMClient().extract_scholarship(
        "Eiffel Excellence Scholarship offered by Campus France.",
        article_url,
        anchor_links=(
            {"text": "Read more", "href": "https://related.example/scholarships/"},
            {"text": "Campus France", "href": "https://www.campusfrance.org/eiffel-scholarship"},
            {"text": "Apply Now", "href": "https://apply.example/form"},
        ),
    )

    assert extracted["official_source"] == "https://www.campusfrance.org/eiffel-scholarship"
    assert extracted["application_url"] == "https://apply.example/form"


def test_generic_neutral_external_link_is_not_guessed_as_official():
    article_url = "https://opportunitiescircle.com/sample-scholarship/"
    extracted = DeterministicLLMClient().extract_scholarship(
        "A scholarship opportunity for graduate students.",
        article_url,
        anchor_links=(
            {"text": "Read more", "href": "https://unrelated.example/"},
        ),
    )

    assert extracted["official_source"] is None


def test_missing_destinations_are_warnings_not_invented_urls():
    article_url = "https://fullyscholarships.com/eiffel-excellence-scholarship-2027/"
    report = validate(
        ExtractedDocument(
            document_id="local-fixture",
            source_url=article_url,
            scholarship=ExtractedScholarship(
                scholarship_name="Eiffel Excellence Scholarship",
                application_url=None,
                official_source=None,
            ),
        )
    )

    assert report.is_valid
    assert {issue.field for issue in report.issues} == {"application_url", "official_source"}
    assert all(issue.severity == "warning" for issue in report.issues)


def test_pipeline_passes_anchor_hrefs_to_extractor():
    article_url = "https://opportunitiescircle.com/sample-scholarship/"
    cleaned = CleanedDocument(
        document_id="local-fixture",
        source_id="local-source",
        source_url=article_url,
        content_type="html",
        clean_text="A scholarship opportunity.",
        page_title="Sample Scholarship 2027",
        headings=["Sample Scholarship 2027"],
        anchors=["Official Site", "Apply Now"],
        anchor_links=[
            AnchorLink(text="Official Site", href="https://official.example/program"),
            AnchorLink(text="Apply Now", href="https://apply.example/form"),
        ],
    )

    result = _invoke_client(DeterministicLLMClient(), cleaned)

    assert result.scholarship.official_source == "https://official.example/program"
    assert result.scholarship.application_url == "https://apply.example/form"
