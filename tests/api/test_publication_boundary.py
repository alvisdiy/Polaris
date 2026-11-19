"""The publication boundary, enforced from one predicate.

M9.1 Phase 6. The public detail endpoint loaded any record by id and then
compared ``extraction_status`` against the literal string ``"approved"`` in the
router — a fourth copy of a rule that already lived in
``services/review/publication.py`` and in three repository methods. It worked,
which is exactly why it was dangerous: the rule it enforced had a second source
of truth that nothing tested.

These tests pin the two halves of the boundary:

    public   -> only APPROVED records, decided by the canonical predicate
    internal -> everything, because review has to be able to reach it

Everything runs inside `exploration_session`, so no row reaches the shared
development database.
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
from services.review.publication import PUBLISHED_STATE, is_published, published_filter
from services.scholarship.repository import ScholarshipRepository

pytestmark = pytest.mark.api

PUBLIC = "/api/v1/scholarships"
REVIEW = "/api/v1/admin/review"

UNPUBLISHED_STATES = (
    ReviewStatus.PENDING_REVIEW,
    ReviewStatus.REJECTED,
    ReviewStatus.NEEDS_CORRECTION,
)


@pytest.fixture
def world(exploration_session):
    """A provider and source, plus one scholarship per review state."""
    session = exploration_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"PUBBOUND_{suffix.upper()}"[:32],
        provider_name="Ministry of Education, Japan",
        provider_type=ProviderType.GOVERNMENT,
        country_id=country.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Publication boundary source {suffix}",
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

    def make(state: str) -> Scholarship:
        record = Scholarship(
            scholarship_name=f"Publication Boundary {state} {suffix}",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Engineering"],
            official_page_url=f"https://www.studyinjapan.go.jp/{suffix}/scholarship.html",
            application_url=f"https://www.studyinjapan.go.jp/{suffix}/apply.html",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status=state,
            deadline_state="active",
            provenance_origin="exploration",
            identity_key=uuid.uuid4().hex,
        )
        session.add(record)
        session.flush()
        return record

    approved = make(ReviewStatus.APPROVED)
    unpublished = {state: make(state) for state in UNPUBLISHED_STATES}
    session.flush()
    return {"approved": approved, "unpublished": unpublished, "session": session}


@pytest.fixture
def public_client(client, world, monkeypatch):
    """Public routes read the isolated session instead of the shared one."""
    from api.routers import recommendations as recommendations_module
    from api.routers import scholarships as scholarships_module

    monkeypatch.setattr(scholarships_module, "SessionLocal", lambda: world["session"])
    monkeypatch.setattr(recommendations_module, "SessionLocal", lambda: world["session"])
    return client


@pytest.fixture
def review_client(client, world, monkeypatch):
    """Review routes read the isolated session instead of the shared one."""
    from api.routers import review as review_module

    monkeypatch.setattr(review_module, "SessionLocal", lambda: world["session"])
    return client


class TestCanonicalPredicate:
    """There is one rule, and the state machine points at it."""

    def test_published_state_is_the_review_status(self):
        assert PUBLISHED_STATE == ReviewStatus.APPROVED == "approved"

    def test_is_published_agrees_with_the_column(self, world):
        assert is_published(world["approved"])
        for record in world["unpublished"].values():
            assert not is_published(record)

    def test_published_filter_matches_the_loaded_rows(self, world):
        """The SQL criterion and the Python predicate cannot disagree."""
        rows = (
            world["session"]
            .query(Scholarship)
            .filter(published_filter(), Scholarship.country_id == world["approved"].country_id)
            .all()
        )
        published = {str(r.scholarship_id) for r in rows}
        assert str(world["approved"].scholarship_id) in published
        for record in world["unpublished"].values():
            assert str(record.scholarship_id) not in published


class TestPublicVisibility:
    def test_approved_record_is_visible(self, public_client, world):
        sid = world["approved"].scholarship_id
        response = public_client.get(f"{PUBLIC}/{sid}")
        assert response.status_code == 200, response.text
        assert response.json()["scholarship_id"] == str(sid)

    def test_approved_record_is_listed(self, public_client, world):
        name = world["approved"].scholarship_name
        response = public_client.get(PUBLIC, params={"q": name, "limit": 50})
        assert response.status_code == 200
        assert name in [r["scholarship_name"] for r in response.json()["results"]]

    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_unpublished_detail_is_a_404(self, public_client, world, state):
        sid = world["unpublished"][state].scholarship_id
        assert public_client.get(f"{PUBLIC}/{sid}").status_code == 404

    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_unpublished_record_is_not_listed(self, public_client, world, state):
        name = world["unpublished"][state].scholarship_name
        response = public_client.get(PUBLIC, params={"q": name, "limit": 50})
        assert response.status_code == 200
        assert name not in [r["scholarship_name"] for r in response.json()["results"]]

    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_unpublished_record_is_not_searchable(self, public_client, world, state):
        """Search and list are different queries; both must obey the rule."""
        name = world["unpublished"][state].scholarship_name
        response = public_client.get(PUBLIC, params={"country": "Japan", "limit": 100})
        assert response.status_code == 200
        assert name not in [r["scholarship_name"] for r in response.json()["results"]]

    def test_unknown_id_is_a_404(self, public_client):
        assert public_client.get(f"{PUBLIC}/{uuid.uuid4()}").status_code == 404

    def test_malformed_id_is_a_404_not_a_500(self, public_client):
        assert public_client.get(f"{PUBLIC}/not-a-uuid").status_code == 404


class TestRepositoryReadPaths:
    def test_published_read_returns_approved_only(self, world):
        repo = ScholarshipRepository(world["session"])
        assert repo.get_published_by_id(world["approved"].scholarship_id) is not None
        for record in world["unpublished"].values():
            assert repo.get_published_by_id(record.scholarship_id) is None

    def test_internal_read_still_reaches_unpublished(self, world):
        """Review, acquisition and curation depend on this staying unfiltered."""
        repo = ScholarshipRepository(world["session"])
        for record in world["unpublished"].values():
            assert repo.get_by_id(record.scholarship_id) is not None


class TestAdminAndReviewStillSeeEverything:
    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_review_packet_reaches_unpublished(self, review_client, world, state):
        sid = world["unpublished"][state].scholarship_id
        response = review_client.get(f"{REVIEW}/scholarships/{sid}")
        assert response.status_code == 200, response.text
        assert response.json()["extraction_status"] == state

    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_review_queue_lists_unpublished(self, review_client, world, state):
        sid = str(world["unpublished"][state].scholarship_id)
        response = review_client.get(
            f"{REVIEW}/scholarships", params={"state": "all", "limit": 200}
        )
        assert response.status_code == 200
        assert sid in [r["scholarship_id"] for r in response.json()["results"]]

    @pytest.mark.parametrize("state", UNPUBLISHED_STATES)
    def test_review_workshop_can_correct_unpublished(self, review_client, world, state):
        sid = world["unpublished"][state].scholarship_id
        response = review_client.patch(
            f"{REVIEW}/scholarships/{sid}",
            json={
                "changes": {"field_of_study": ["Physics"]},
                "reason": "corrected in the workshop",
                "actor": "reviewer-boundary",
                "requeue": False,
            },
        )
        assert response.status_code == 200, response.text


class TestMatchingSeesPublishedOnly:
    def test_matching_dataset_excludes_unpublished(self, world):
        from services.matching.service import MatchingService

        session = world["session"]
        loaded = MatchingService(session)._repository.get_all_approved()
        loaded_ids = {str(s.scholarship_id) for s in loaded}

        assert str(world["approved"].scholarship_id) in loaded_ids
        for record in world["unpublished"].values():
            assert str(record.scholarship_id) not in loaded_ids

    def test_a_recommendation_never_names_an_unpublished_record(self, public_client, world):
        from api.schemas import RecommendationRequest

        payload = RecommendationRequest(
            target_country="Japan",
            degree="Master",
            field_of_study=["Engineering"],
            current_gpa=3.5,
            ielts_score=7.0,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        response = public_client.post(
            "/api/v1/recommendations", json=payload.model_dump(mode="json")
        )
        assert response.status_code == 200, response.text
        body = response.json()
        names = {m["scholarship_name"] for m in body["results"]}
        for record in world["unpublished"].values():
            assert record.scholarship_name not in names
