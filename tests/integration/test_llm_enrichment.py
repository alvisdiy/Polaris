"""The LLM pass end to end: proposals land through ReviewService.correct.

This is the integration the unit tests cannot show: an evidence-verified
proposal, applied the way scripts/enrich_records.py applies it, actually
fills the requirement row and records the LLM actor in provenance —
while the record stays in pending_review for a human to judge.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.intelligence.extraction import ALL_FIELDS, propose_llm_completions
from services.review import ReviewService, ReviewStatus

pytestmark = pytest.mark.integration

PAGE = (
    "Applicants must hold a minimum IELTS score of 6.5 overall. "
    "Interviews will be held on 2027-02-10."
)


class StubClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls_made = 0

    def generate_json(self, prompt: str) -> dict:
        self.calls_made += 1
        return self.reply


@pytest.fixture
def pending_record(exploration_session):
    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"LLM_{suffix.upper()}"[:32],
        provider_name="LLM Ministry",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"LLM source {suffix}",
        country_id=jp.country_id,
        official_url=f"https://example.org/{suffix}/",
        crawl_entry_url=f"https://example.org/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()
    record = Scholarship(
        scholarship_name="LLM Enrichment Award",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering"],
        official_page_url="https://example.org/award",
        provider_id=provider.provider_id,
        country_id=jp.country_id,
        source_id=source.source_id,
        extraction_status=ReviewStatus.PENDING_REVIEW,
        provenance_origin="exploration",
        identity_key=uuid.uuid4().hex,
    )
    session.add(record)
    session.flush()
    return record


def test_llm_proposals_fill_fields_through_the_review_path(
    exploration_session, pending_record
):
    current = {field: None for field in ALL_FIELDS}
    client = StubClient(
        {
            "minimum_ielts": {
                "value": 6.5,
                "evidence": "Applicants must hold a minimum IELTS score of 6.5 overall.",
            },
            "interview_date": {
                "value": "2027-02-10",
                "evidence": "Interviews will be held on 2027-02-10.",
            },
        }
    )
    proposals = propose_llm_completions(
        current=current, text=PAGE, today=date(2026, 11, 24), client=client
    )
    assert {p.field for p in proposals} == {"minimum_ielts", "ielts_required", "interview_date"}

    service = ReviewService(exploration_session)
    for proposal in proposals:
        service.correct(
            str(pending_record.scholarship_id),
            actor="llm-enrichment",
            changes=proposal.as_change(),
            reason=f'gemini extraction (evidence-verified): "{proposal.evidence[:160]}"',
            evidence_url=pending_record.official_page_url,
            requeue=False,
        )

    exploration_session.refresh(pending_record)
    assert pending_record.requirement.minimum_ielts == 6.5
    assert pending_record.requirement.ielts_required is True
    assert str(pending_record.timeline.interview_date) == "2027-02-10"
    # Still a proposal in the only sense that matters: a human has not
    # approved this record, and the LLM pass must not change that.
    assert pending_record.extraction_status == ReviewStatus.PENDING_REVIEW
    provenance = pending_record.field_provenance or {}
    assert provenance["minimum_ielts"]["actor"] == "llm-enrichment"
