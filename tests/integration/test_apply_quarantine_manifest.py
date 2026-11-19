"""The quarantine manifest and its applier, against an isolated session.

Catalogue Trust Sprint, Task 2. The manifest decides which published records
leave the public catalogue; ``scripts/apply_quarantine_manifest.py`` is the only
thing that acts on it. What has to hold:

  * a signed entry for a placeholder-source or non-scholarship record is
    rejected **through ReviewService**, so the audit row, the version row and
    the provenance survive;
  * records the manifest does not quarantine — valid scholarships, duplicate
    reviews, metadata-only defects — are never touched;
  * a manifest written against a status the record no longer has fails safely,
    with nothing written at all;
  * a dry run writes nothing, twice over, and re-running an execution does not
    produce a second audit row.

Everything here runs on ``exploration_session``, which is bound to a rolled-back
transaction, so no test in this file can reach the shared catalogue. The
``run()`` calls pass ``session_factory`` so the script drives that same isolated
session rather than opening its own.
"""

from __future__ import annotations

import json
import uuid

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from scripts.apply_quarantine_manifest import (
    DEFAULT_MANIFEST,
    EXIT_OK,
    EXIT_PREFLIGHT,
    EXIT_USAGE,
    ManifestError,
    apply_plan,
    build_plan,
    is_signed,
    load_manifest,
    run,
    status_counts,
    validate_manifest,
)
from services.review import ReviewService, ReviewStatus

SIGNED = "reviewer-1"
SIGNED_AT = "2026-10-15T10:00:00Z"


@pytest.fixture
def session(exploration_session):
    return exploration_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


def _origin(session, jp_country):
    """A provider and a source of this test's own, cached per session."""
    cached = getattr(session, "_quarantine_origin_refs", None)
    if cached is not None:
        return cached

    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"QUAR_{suffix}".upper()[:32],
        provider_name="Quarantine Fixture Foundation",
        provider_type=ProviderType.FOUNDATION,
        country_id=jp_country.country_id,
        official_url=f"https://quarantine-{suffix}.ac.uk/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Quarantine Fixture {suffix}",
        country_id=jp_country.country_id,
        official_url=f"https://quarantine-{suffix}.ac.uk/scholarships",
        crawl_entry_url=f"https://quarantine-{suffix}.ac.uk/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()
    session._quarantine_origin_refs = (provider, source)
    return provider, source


def make_record(session, jp_country, *, name, url, status=ReviewStatus.APPROVED):
    """One publishable-looking record in the requested state."""
    provider, source = _origin(session, jp_country)
    record = Scholarship(
        scholarship_name=name,
        provider_id=provider.provider_id,
        country_id=jp_country.country_id,
        source_id=source.source_id,
        official_page_url=url,
        application_url=f"{url.rstrip('/')}/apply",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering"],
        extraction_status=status,
        provenance_origin="exploration",
    )
    session.add(record)
    session.flush()
    return record


def entry_for(record, **overrides):
    """A manifest entry for ``record``, unsigned unless the test signs it."""
    base = {
        "scholarship_id": str(record.scholarship_id),
        "current_status": ReviewStatus.APPROVED,
        "category": "A",
        "title": record.scholarship_name,
        "provider": "Quarantine Fixture Foundation",
        "country": "JP",
        "official_url": record.official_page_url,
        "evidence": [{"fact": "fixture evidence", "how": "db-query", "observed": "2026-10-15"}],
        "proposed_action": "reject",
        "confidence": "high",
        "human_review_required": False,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    base.update(overrides)
    return base


def signed(entry):
    entry["reviewed_by"] = SIGNED
    entry["reviewed_at"] = SIGNED_AT
    return entry


def write_manifest(tmp_path, entries, **top):
    payload = {"manifest_version": 1, "generated_at": "2026-10-15", "entries": entries}
    payload.update(top)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def history_of(session, record):
    actions = (
        session.query(ScholarshipReviewAction)
        .filter(ScholarshipReviewAction.scholarship_id == record.scholarship_id)
        .all()
    )
    versions = (
        session.query(ScholarshipVersion)
        .filter(ScholarshipVersion.scholarship_id == record.scholarship_id)
        .all()
    )
    return actions, versions


# --------------------------------------------------------------- validation


class TestManifestValidation:
    def test_the_shipped_manifest_is_well_formed(self):
        """The artifact in the repository must be one the applier accepts."""
        assert validate_manifest(load_manifest(DEFAULT_MANIFEST)) == []

    def test_the_shipped_manifest_signs_nothing(self):
        """Preparation must leave every entry unsigned, so nothing can run."""
        manifest = load_manifest(DEFAULT_MANIFEST)
        assert all(not is_signed(e) for e in manifest["entries"])

    def test_missing_fields_are_all_reported(self):
        manifest = {"entries": [{"scholarship_id": "not-a-uuid"}]}
        errors = validate_manifest(manifest)
        assert any("missing field" in e for e in errors)
        assert any("not a UUID" in e for e in errors)

    def test_bad_category_and_action_are_reported(self, jp_country, session):
        record = make_record(session, jp_country, name="Bad", url="https://x.ac.uk/")
        manifest = {"entries": [
            entry_for(record, category="Z", proposed_action="delete-record"),
        ]}
        errors = validate_manifest(manifest)
        assert any("category" in e for e in errors)
        assert any("proposed_action" in e for e in errors)

    def test_duplicate_ids_are_reported(self, jp_country, session):
        record = make_record(session, jp_country, name="Dup", url="https://d.ac.uk/")
        manifest = {"entries": [entry_for(record), entry_for(record)]}
        assert any("duplicate scholarship_id" in e for e in validate_manifest(manifest))

    def test_entry_without_evidence_is_rejected(self, jp_country, session):
        record = make_record(session, jp_country, name="Bare", url="https://b.ac.uk/")
        manifest = {"entries": [entry_for(record, evidence=[])]}
        assert any("no evidence" in e for e in validate_manifest(manifest))

    def test_unreadable_manifest_raises(self, tmp_path):
        with pytest.raises(ManifestError):
            load_manifest(tmp_path / "absent.json")
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with pytest.raises(ManifestError):
            load_manifest(broken)


# ------------------------------------------------------------------ dry run


class TestDryRun:
    def test_dry_run_writes_nothing(self, session, jp_country, tmp_path, capsys):
        record = make_record(
            session, jp_country, name="Placeholder", url="https://example.com/mext"
        )
        session.commit()
        path = write_manifest(tmp_path, [signed(entry_for(record))])
        before = status_counts(session)

        assert run(["--manifest", str(path)], session_factory=lambda: session) == EXIT_OK

        assert status_counts(session) == before
        actions, versions = history_of(session, record)
        assert actions == [] and versions == []
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "counts after: unchanged" in out

    def test_repeated_dry_runs_are_stable(self, session, jp_country, tmp_path):
        record = make_record(session, jp_country, name="Twice", url="https://tw.ac.uk/")
        session.commit()
        path = write_manifest(tmp_path, [signed(entry_for(record))])
        first = status_counts(session)

        assert run(["--manifest", str(path)], session_factory=lambda: session) == EXIT_OK
        assert run(["--manifest", str(path)], session_factory=lambda: session) == EXIT_OK

        assert status_counts(session) == first
        actions, versions = history_of(session, record)
        assert actions == [] and versions == []

    def test_invalid_manifest_exits_with_usage_code(self, tmp_path):
        path = write_manifest(tmp_path, [{"scholarship_id": "nope"}])
        assert run(["--manifest", str(path)]) == EXIT_USAGE

    def test_unreadable_manifest_exits_with_usage_code(self, tmp_path):
        assert run(["--manifest", str(tmp_path / "nope.json")]) == EXIT_USAGE


# ---------------------------------------------------------------- execution


class TestApply:
    def test_placeholder_record_is_rejected_through_the_service(
        self, session, jp_country
    ):
        record = make_record(
            session, jp_country, name="MEXT Scholarship (Test)",
            url="https://example.com/mext",
        )
        session.commit()
        manifest = {"manifest_version": 1, "entries": [signed(entry_for(record))]}

        plan = build_plan(session, manifest)
        assert plan.problems == []
        assert [p.verdict for p in plan.entries] == ["APPLY"]

        result = apply_plan(session, manifest, plan, actor="tester")
        assert result == {"applied": 1}

        session.expire_all()
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.REJECTED
        )

        actions, versions = history_of(session, record)
        assert [a.action for a in actions] == ["rejected"]
        assert actions[0].actor == "tester"
        assert actions[0].previous_state == ReviewStatus.APPROVED
        assert actions[0].new_state == ReviewStatus.REJECTED
        assert "quarantine manifest" in actions[0].reason
        assert "fixture evidence" in actions[0].reason
        assert actions[0].evidence_url == record.official_page_url
        assert len(versions) == 1 and versions[0].version_number == 1

    def test_likely_non_scholarship_record_is_rejected(self, session, jp_country):
        record = make_record(
            session, jp_country,
            name="PhD Studentship: Fixture at Example University",
            url="https://jobs-fixture.ac.uk/job/DTX100/phd-studentship-fixture",
        )
        session.commit()
        manifest = {"entries": [
            signed(entry_for(record, category="B", human_review_required=True))
        ]}

        plan = build_plan(session, manifest)
        apply_plan(session, manifest, plan, actor="tester")
        session.expire_all()

        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.REJECTED
        )

    def test_a_record_not_in_the_manifest_is_untouched(self, session, jp_country):
        quarantined = make_record(
            session, jp_country, name="Quarantine Me", url="https://example.com/x"
        )
        keep = make_record(
            session, jp_country, name="Genuine Scholarship",
            url="https://www.studyinjapan.go.jp/en/mext/",
        )
        session.commit()
        manifest = {"entries": [signed(entry_for(quarantined))]}

        plan = build_plan(session, manifest)
        apply_plan(session, manifest, plan, actor="tester")
        session.expire_all()

        survivor = session.get(Scholarship, keep.scholarship_id)
        assert survivor.extraction_status == ReviewStatus.APPROVED
        assert history_of(session, survivor) == ([], [])

    def test_duplicate_review_entries_are_not_applied(self, session, jp_country):
        record = make_record(
            session, jp_country, name="LPDP Beasiswa Reguler (Master)",
            url="https://lpdp-fixture.go.id/en/beasiswa/umum/beasiswa-reguler/",
        )
        session.commit()
        manifest = {"entries": [
            signed(entry_for(record, category="C", proposed_action="none",
                             human_review_required=True))
        ]}

        plan = build_plan(session, manifest)
        assert [p.verdict for p in plan.entries] == ["SKIP_NOT_EXECUTABLE"]
        assert apply_plan(session, manifest, plan, actor="tester") == {"applied": 0}

        session.expire_all()
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )
        assert history_of(session, record) == ([], [])

    def test_metadata_only_entries_are_not_applied(self, session, jp_country):
        record = make_record(
            session, jp_country, name="SP Undergraduate Scholarship",
            url="https://sp-fixture.edu.sg/admissions/sp-undergraduate-scholarship",
        )
        session.commit()
        manifest = {"entries": [
            signed(entry_for(record, category="D", proposed_action="report_only"))
        ]}

        plan = build_plan(session, manifest)
        assert plan.applicable == []
        assert apply_plan(session, manifest, plan, actor="tester") == {"applied": 0}
        session.expire_all()
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )

    def test_unsigned_entry_is_skipped(self, session, jp_country):
        record = make_record(
            session, jp_country, name="Unsigned", url="https://example.com/unsigned"
        )
        session.commit()
        manifest = {"entries": [entry_for(record)]}   # deliberately not signed

        plan = build_plan(session, manifest)
        assert [p.verdict for p in plan.entries] == ["SKIP_UNSIGNED"]
        assert apply_plan(session, manifest, plan, actor="tester") == {"applied": 0}
        session.expire_all()
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )
        assert history_of(session, record) == ([], [])

    def test_stale_manifest_status_fails_safely(self, session, jp_country):
        """A record that moved after the manifest was written blocks the run."""
        record = make_record(session, jp_country, name="Moved", url="https://m.ac.uk/")
        session.commit()
        ReviewService(session).correct(
            str(record.scholarship_id),
            actor="reviewer",
            changes={"degree": "PhD"},
            reason="corrected after the manifest was written",
        )
        session.commit()
        assert record.extraction_status == ReviewStatus.PENDING_REVIEW

        manifest = {"entries": [signed(entry_for(record))]}
        plan = build_plan(session, manifest)

        assert len(plan.problems) == 1
        assert "manifest expects 'approved' but record is 'pending_review'" in (
            plan.problems[0].detail
        )
        assert plan.applicable == []

        # The refusal happens before any service call, so the trail is empty.
        session.expire_all()
        assert session.get(Scholarship, record.scholarship_id).extraction_status == (
            ReviewStatus.PENDING_REVIEW
        )
        actions, versions = history_of(session, record)
        assert [a.action for a in actions] == ["corrected"]
        assert versions[0].version_number == 1

    def test_a_missing_record_is_a_preflight_problem(self, session, tmp_path):
        """End to end: a manifest naming a record that is not there blocks the run."""
        unknown = str(uuid.uuid4())
        path = write_manifest(tmp_path, [{
            "scholarship_id": unknown,
            "current_status": ReviewStatus.APPROVED,
            "category": "A",
            "title": "Gone",
            "provider": "n/a",
            "country": "JP",
            "official_url": "https://example.com/gone",
            "evidence": [{"fact": "n/a"}],
            "proposed_action": "reject",
            "confidence": "high",
            "human_review_required": False,
            "reviewed_by": SIGNED,
            "reviewed_at": SIGNED_AT,
        }])
        assert run(
            ["--manifest", str(path), "--execute"], session_factory=lambda: session
        ) == EXIT_PREFLIGHT

    def test_execution_is_idempotent(self, session, jp_country):
        record = make_record(
            session, jp_country, name="Twice Applied", url="https://example.com/twice"
        )
        session.commit()
        manifest = {"entries": [signed(entry_for(record))]}

        first = build_plan(session, manifest)
        assert apply_plan(session, manifest, first, actor="tester") == {"applied": 1}
        actions, versions = history_of(session, record)
        assert len(actions) == 1 and len(versions) == 1

        # A second run sees the record already where the manifest wants it.
        second = build_plan(session, manifest)
        assert [p.verdict for p in second.entries] == ["ALREADY_DONE"]
        assert second.problems == []
        assert apply_plan(session, manifest, second, actor="tester") == {"applied": 0}

        session.expire_all()
        actions, versions = history_of(session, record)
        assert len(actions) == 1, "a repeated run must not add a second audit row"
        assert len(versions) == 1

    def test_provenance_survives_a_rejection(self, session, jp_country):
        """Quarantine changes the status and nothing else about the record."""
        record = make_record(
            session, jp_country, name="With Provenance", url="https://p.ac.uk/x"
        )
        record.field_provenance = {"degree": {"origin": "machine_extracted"}}
        record.quality_report = {"publishable": True, "blocking": []}
        session.commit()
        provenance_before = dict(record.field_provenance)
        quality_before = dict(record.quality_report)

        manifest = {"entries": [signed(entry_for(record))]}
        plan = build_plan(session, manifest)
        apply_plan(session, manifest, plan, actor="tester")

        session.expire_all()
        row = session.get(Scholarship, record.scholarship_id)
        assert row.extraction_status == ReviewStatus.REJECTED
        assert row.field_provenance == provenance_before
        assert row.quality_report == quality_before
        assert row.scholarship_name == record.scholarship_name
        assert row.official_page_url == record.official_page_url

    def test_counts_before_and_after_are_reported(self, session, jp_country):
        before = status_counts(session)
        record = make_record(
            session, jp_country, name="Counted", url="https://example.com/counted"
        )
        session.commit()
        with_approved = status_counts(session)
        assert with_approved[ReviewStatus.APPROVED] == before[ReviewStatus.APPROVED] + 1

        manifest = {"entries": [signed(entry_for(record))]}
        plan = build_plan(session, manifest)
        apply_plan(session, manifest, plan, actor="tester")

        after = status_counts(session)
        assert after[ReviewStatus.APPROVED] == with_approved[ReviewStatus.APPROVED] - 1
        assert after[ReviewStatus.REJECTED] == (
            with_approved.get(ReviewStatus.REJECTED, 0) + 1
        )


# --------------------------------------------------------------- guard rails


class TestRefusals:
    def test_execute_without_signed_entries_changes_nothing(
        self, session, jp_country, tmp_path, capsys
    ):
        record = make_record(
            session, jp_country, name="Pending Signature", url="https://example.com/wait"
        )
        session.commit()
        path = write_manifest(tmp_path, [entry_for(record)])
        before = status_counts(session)

        assert run(
            ["--manifest", str(path), "--execute", "--actor", "tester"],
            session_factory=lambda: session,
        ) == EXIT_OK

        assert status_counts(session) == before
        assert history_of(session, record) == ([], [])
        assert "nothing to apply" in capsys.readouterr().out

    def test_report_only_and_duplicate_entries_are_never_executed(
        self, session, jp_country, tmp_path
    ):
        """Two non-quarantine decisions plus one quarantine, all signed."""
        survivor = make_record(
            session, jp_country, name="Cleared Duplicate", url="https://c.ac.uk/a"
        )
        defect = make_record(
            session, jp_country, name="Metadata Defect", url="https://d.ac.uk/b"
        )
        to_quarantine = make_record(
            session, jp_country, name="Placeholder", url="https://example.com/mext"
        )
        session.commit()
        path = write_manifest(tmp_path, [
            signed(entry_for(survivor, category="C", proposed_action="none")),
            signed(entry_for(defect, category="D", proposed_action="report_only")),
            signed(entry_for(to_quarantine)),
        ])
        before = status_counts(session)

        assert run(
            ["--manifest", str(path), "--execute", "--actor", "tester"],
            session_factory=lambda: session,
        ) == EXIT_OK

        session.expire_all()
        assert session.get(Scholarship, survivor.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )
        assert session.get(Scholarship, defect.scholarship_id).extraction_status == (
            ReviewStatus.APPROVED
        )
        assert session.get(Scholarship, to_quarantine.scholarship_id).extraction_status == (
            ReviewStatus.REJECTED
        )
        after = status_counts(session)
        assert after[ReviewStatus.APPROVED] == before[ReviewStatus.APPROVED] - 1
        assert after[ReviewStatus.REJECTED] == before.get(ReviewStatus.REJECTED, 0) + 1
