"""Per-record meta injection for detail pages.

Unit tests pin the composition and escaping (they run everywhere).
HTTP tests pin the wiring — published record gets its own title and
JSON-LD, an unpublished record gets the plain shell so its name never
leaks into meta — and are skipped where the frontend build is absent
(CI's pytest job does not build the SPA; the route is registered only
when frontend/dist exists, like the SPA fallback itself).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from api.detail_meta import build_detail_meta, render_detail_html

SHELL = """<!DOCTYPE html>
<html><head>
<meta name="description" content="Generic description." />
<meta property="og:type" content="website" />
<meta property="og:title" content="Polaris | Scholarship Intelligence" />
<meta property="og:description" content="Generic description." />
<title>Polaris | Scholarship Intelligence</title>
</head><body><div id="app"></div></body></html>"""


def _meta(**overrides):
    base = dict(
        name="Brightpath Scholars Award",
        provider_name="Zephyr Education Trust",
        country_name="Japan",
        degree="Master",
        funding_type="Fully Funded",
        deadline=date(2027, 3, 1),
        field_of_study=["Astrophysics"],
        canonical_url="https://polaris.example/scholarships/abc",
    )
    base.update(overrides)
    return build_detail_meta(**base)


class TestBuildMeta:
    def test_title_and_description_use_real_fields(self):
        meta = _meta()
        assert meta.title == "Brightpath Scholars Award | Polaris"
        assert "Zephyr Education Trust" in meta.description
        assert "Japan" in meta.description
        assert "2027-03-01" in meta.description

    def test_missing_fields_shorten_rather_than_invent(self):
        meta = _meta(provider_name=None, country_name=None, deadline=None, degree=None)
        assert "by None" not in meta.description
        assert "deadline" not in meta.description.lower()

    def test_json_ld_is_a_programme_with_provider(self):
        meta = _meta()
        assert meta.json_ld["@type"] == "EducationalOccupationalProgram"
        assert meta.json_ld["provider"]["name"] == "Zephyr Education Trust"
        assert meta.json_ld["url"] == meta.canonical_url


class TestRender:
    def test_injects_title_og_canonical_and_json_ld(self):
        out = render_detail_html(SHELL, _meta())
        assert "<title>Brightpath Scholars Award | Polaris</title>" in out
        assert 'property="og:title" content="Brightpath Scholars Award | Polaris"' in out
        assert 'property="og:type" content="article"' in out
        assert 'rel="canonical" href="https://polaris.example/scholarships/abc"' in out
        assert '"EducationalOccupationalProgram"' in out
        assert "Polaris | Scholarship Intelligence</title>" not in out

    def test_escapes_extracted_values(self):
        out = render_detail_html(SHELL, _meta(name='A "quoted" <script>alert(1)</script> award'))
        assert "<script>alert(1)</script> award | Polaris</title>" not in out
        assert "&lt;script&gt;" in out
        # The JSON-LD block must not be breakable by a closing tag in data.
        assert "</script> award" not in out


DIST_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"

pytestmark_http = pytest.mark.skipif(
    not DIST_INDEX.exists(), reason="frontend build (dist/) not present in this environment"
)


@pytest.fixture
def meta_world(exploration_session):
    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.scholarship import Scholarship
    from database.models.source_registry import SourceRegistry
    from services.review import ReviewStatus

    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"META_{suffix.upper()}"[:32],
        provider_name="Meta Ministry",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Meta source {suffix}",
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

    def make(state, name):
        record = Scholarship(
            scholarship_name=name,
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Engineering"],
            official_page_url="https://example.org/p",
            provider_id=provider.provider_id,
            country_id=jp.country_id,
            source_id=source.source_id,
            extraction_status=state,
            deadline_state="active",
            provenance_origin="exploration",
            identity_key=uuid.uuid4().hex,
        )
        session.add(record)
        session.flush()
        return record

    return {
        "published": make(ReviewStatus.APPROVED, f"Meta Published {suffix}"),
        "pending": make(ReviewStatus.PENDING_REVIEW, f"Meta Pending {suffix}"),
    }


@pytestmark_http
class TestDetailMetaHttp:
    @pytest.fixture(autouse=True)
    def _patch_session(self, meta_world, exploration_session, monkeypatch):
        monkeypatch.setattr("database.session.SessionLocal", lambda: exploration_session)

    def test_published_record_gets_its_own_title(self, client, meta_world):
        record = meta_world["published"]
        response = client.get(f"/scholarships/{record.scholarship_id}")
        assert response.status_code == 200
        assert f"<title>{record.scholarship_name} | Polaris</title>" in response.text
        assert '"EducationalOccupationalProgram"' in response.text
        assert response.headers.get("cache-control") == "public, max-age=300"

    def test_unpublished_record_gets_the_plain_shell(self, client, meta_world):
        record = meta_world["pending"]
        response = client.get(f"/scholarships/{record.scholarship_id}")
        assert response.status_code == 200
        assert record.scholarship_name not in response.text

    def test_malformed_id_gets_the_plain_shell(self, client):
        response = client.get("/scholarships/not-a-uuid")
        assert response.status_code == 200
        assert "<title>Polaris | Scholarship Intelligence</title>" in response.text


class TestFundingAmountMeta:
    def test_amount_label_uses_the_stated_period(self):
        meta = _meta(funding_amount=Decimal("2100"), funding_currency="EUR", funding_period="per_month")
        assert "€2,100/month" in meta.description

    def test_amount_without_period_is_not_rendered(self):
        meta = _meta(funding_amount=Decimal("2100"), funding_currency="EUR", funding_period=None)
        assert "2,100" not in meta.description

    def test_source_description_leads(self):
        meta = _meta(
            description="This award supports graduate research in astrophysics at Japanese universities."
        )
        assert meta.description.startswith("This award supports graduate research")
