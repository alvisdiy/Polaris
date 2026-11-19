"""API tests for the internal review / curation endpoints.

These test the HTTP contract: status codes, response shape, and which errors
the API refuses to perform. The curation rules themselves are covered against
the database in tests/integration/test_review_service.py.

Writes are bound to a rollback-only session by patching the router's
``SessionLocal``. The router is a transport layer that manages its own session,
which is right for production and wrong for tests that would otherwise commit
test rows into the shared development database.
"""

from __future__ import annotations

import uuid

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.review import ReviewStatus

pytestmark = pytest.mark.api

BASE = "/api/v1/admin/review"


@pytest.fixture
def origin_refs(exploration_session):
    """A provider and source for the record under review.

    Created per test because the isolation fixture empties the country's
    exploration state, which is what keeps these tests independent of real
    runs in the shared database.
    """
    session = exploration_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"TEST_{suffix}".upper()[:32],
        provider_name="Ministry of Education, Japan",
        provider_type=ProviderType.GOVERNMENT,
        country_id=country.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Study in Japan {suffix}",
        country_id=country.country_id,
        official_url=f"https://www.studyinjapan.go.jp/{suffix}/",
        crawl_entry_url=f"https://www.studyinjapan.go.jp/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()
    return country, provider, source


@pytest.fixture
def pending_scholarship(exploration_session, origin_refs):
    country, provider, source = origin_refs
    scholarship = Scholarship(
        scholarship_name="Monbukagakusho Scholarship 2027",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering"],
        official_page_url="https://www.studyinjapan.go.jp/en/",
        application_url="https://www.studyinjapan.go.jp/en/apply/",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status=ReviewStatus.PENDING_REVIEW,
        provenance_origin="exploration",
    )
    exploration_session.add(scholarship)
    exploration_session.flush()
    return scholarship


@pytest.fixture
def review_client(client, exploration_session, monkeypatch):
    """Test client whose review routes write inside the rolled-back transaction."""
    from api.routers import review as review_module

    monkeypatch.setattr(review_module, "SessionLocal", lambda: exploration_session)
    return client


class TestQueue:
    def test_queue_lists_pending_records(self, review_client, pending_scholarship):
        response = review_client.get(
            f"{BASE}/scholarships", params={"country_id": str(pending_scholarship.country_id)}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        row = next(
            r for r in body["results"] if r["scholarship_id"] == str(pending_scholarship.scholarship_id)
        )
        assert row["extraction_status"] == ReviewStatus.PENDING_REVIEW
        assert row["provenance_origin"] == "exploration"

    def test_queue_can_show_every_state(self, review_client, pending_scholarship):
        response = review_client.get(f"{BASE}/scholarships", params={"state": "all"})
        assert response.status_code == 200
        ids = {r["scholarship_id"] for r in response.json()["results"]}
        assert str(pending_scholarship.scholarship_id) in ids

    def test_invalid_country_is_404_not_500(self, review_client):
        response = review_client.get(f"{BASE}/scholarships", params={"country_id": "not-a-uuid"})
        assert response.status_code == 404


class TestDetail:
    def test_packet_contains_everything_a_reviewer_needs(self, review_client, pending_scholarship):
        response = review_client.get(f"{BASE}/scholarships/{pending_scholarship.scholarship_id}")
        assert response.status_code == 200
        body = response.json()

        assert body["identity"]["provider_name"] == "Ministry of Education, Japan"
        assert body["identity"]["source_verification_state"] == "VERIFIED"
        assert body["eligibility"]["degree"] == "Master"
        assert "tuition_fee" in body["funding"]
        assert "application_deadline" in body["timeline"]
        # The provenance chain the M9 brief requires, exposed as data.
        assert body["identity"]["source_official_url"].startswith("https://")
        assert "identity" in body["quality"]["fields"]
        assert body["quality"]["publishable"] is True

    def test_unknown_id_is_404(self, review_client):
        assert review_client.get(f"{BASE}/scholarships/{uuid.uuid4()}").status_code == 404

    def test_malformed_id_is_404_not_500(self, review_client):
        """A malformed id is a client error; a 500 here would be a defect."""
        assert review_client.get(f"{BASE}/scholarships/not-a-uuid").status_code == 404


class TestDecisions:
    def test_approve_publishes_and_records_actor(self, review_client, pending_scholarship):
        sid = str(pending_scholarship.scholarship_id)
        response = review_client.post(
            f"{BASE}/scholarships/{sid}/approve",
            json={"actor": "alice", "reason": "verified against the official page"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["new_state"] == ReviewStatus.APPROVED
        assert body["previous_state"] == ReviewStatus.PENDING_REVIEW
        assert body["version_id"] is not None

        detail = review_client.get(f"{BASE}/scholarships/{sid}").json()
        assert detail["reviewed_by"] == "alice"
        assert detail["history"][-1]["action"] == "approved"
        assert detail["history"][-1]["actor"] == "alice"

    def test_approve_without_actor_is_rejected(self, review_client, pending_scholarship):
        response = review_client.post(
            f"{BASE}/scholarships/{pending_scholarship.scholarship_id}/approve", json={}
        )
        assert response.status_code == 422

    def test_blocked_record_is_422_not_500(self, review_client, exploration_session, origin_refs):
        country, provider, source = origin_refs
        nameless = Scholarship(
            scholarship_name="Unknown Scholarship",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Engineering"],
            official_page_url="https://www.studyinjapan.go.jp/en/",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            provenance_origin="exploration",
        )
        exploration_session.add(nameless)
        exploration_session.flush()

        response = review_client.post(
            f"{BASE}/scholarships/{nameless.scholarship_id}/approve", json={"actor": "alice"}
        )
        assert response.status_code == 422
        assert "identity" in response.json()["detail"]

    def test_reject_requires_a_reason(self, review_client, pending_scholarship):
        response = review_client.post(
            f"{BASE}/scholarships/{pending_scholarship.scholarship_id}/reject",
            json={"actor": "bob", "reason": "   "},
        )
        assert response.status_code == 409

    def test_invalid_transition_is_409(self, review_client, pending_scholarship):
        """Approving a rejected record is a state conflict, not a bad request."""
        sid = str(pending_scholarship.scholarship_id)
        review_client.post(f"{BASE}/scholarships/{sid}/reject", json={"actor": "bob", "reason": "not a scholarship"})

        response = review_client.post(f"{BASE}/scholarships/{sid}/approve", json={"actor": "alice"})
        assert response.status_code == 409


class TestCorrections:
    def test_patch_records_the_change_and_requeues(self, review_client, pending_scholarship):
        sid = str(pending_scholarship.scholarship_id)
        response = review_client.patch(
            f"{BASE}/scholarships/{sid}",
            json={
                "changes": {"deadline": "2027-05-01"},
                "reason": "official page states 1 May 2027",
                "actor": "carol",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["field_changes"][0]["new"] == "2027-05-01"

        detail = review_client.get(f"{BASE}/scholarships/{sid}").json()
        assert detail["timeline"]["application_deadline"] == "2027-05-01"
        assert detail["versions"][-1]["version_number"] == 1

    def test_unknown_field_is_rejected_not_ignored(self, review_client, pending_scholarship):
        response = review_client.patch(
            f"{BASE}/scholarships/{pending_scholarship.scholarship_id}",
            json={"changes": {"not_a_field": 1}, "reason": "typo", "actor": "carol"},
        )
        assert response.status_code == 409
        assert "not_a_field" in response.json()["detail"]

    def test_request_correction_moves_the_record_out_of_the_queue(
        self, review_client, pending_scholarship
    ):
        sid = str(pending_scholarship.scholarship_id)
        response = review_client.post(
            f"{BASE}/scholarships/{sid}/request-correction",
            json={"actor": "carol", "reason": "deadline needs checking"},
        )
        assert response.status_code == 200
        assert response.json()["new_state"] == ReviewStatus.NEEDS_CORRECTION


class TestMetrics:
    def test_metrics_separate_origins(self, review_client, exploration_session, origin_refs):
        """Manual seeds must never be able to pose as discovery output."""
        country, provider, source = origin_refs
        for name, origin in (("Explored A", "exploration"), ("Seeded B", "seed_script")):
            exploration_session.add(Scholarship(
                scholarship_name=name,
                degree="Master",
                funding_type="Fully Funded",
                field_of_study=[],
                official_page_url="https://www.studyinjapan.go.jp/en/",
                provider_id=provider.provider_id,
                country_id=country.country_id,
                source_id=source.source_id,
                extraction_status=ReviewStatus.PENDING_REVIEW,
                provenance_origin=origin,
            ))
        exploration_session.flush()

        body = review_client.get(
            f"{BASE}/metrics", params={"country_id": str(country.country_id)}
        ).json()
        assert body["by_origin"]["exploration"] == 1
        assert body["by_origin"]["seed_script"] == 1
        assert body["pending_review"] == 2
        assert body["approval_rate"] is None

    def test_approval_rate_uses_decided_records_only(self, review_client, exploration_session, origin_refs):
        country, provider, source = origin_refs
        for state in (ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.PENDING_REVIEW):
            exploration_session.add(Scholarship(
                scholarship_name=f"Record {state}",
                degree="Master",
                funding_type="Fully Funded",
                field_of_study=[],
                official_page_url="https://www.studyinjapan.go.jp/en/",
                provider_id=provider.provider_id,
                country_id=country.country_id,
                source_id=source.source_id,
                extraction_status=state,
                provenance_origin="exploration",
            ))
        exploration_session.flush()

        body = review_client.get(
            f"{BASE}/metrics", params={"country_id": str(country.country_id)}
        ).json()
        # 1 approved, 1 rejected, 1 undecided: the pending record must not
        # inflate either rate.
        assert body["approval_rate"] == 0.5
        assert body["rejection_rate"] == 0.5
        assert body["undecided"] == 1
