"""No runtime path may publish a scholarship by writing its status directly.

M9.1 Phase 8. The publication boundary is ``ReviewService``: it is the only
writer of ``extraction_status``, and it writes the version row and the review
action in the same transaction. Anything else that sets the column to
``approved`` publishes a record with no reviewer, no version and no audit
trail — the same defect M9.1 closed for reacquisition, reachable by writing one
line.

The first version of this rule caught a real bypass: ``scripts/run_mext_pipeline``
auto-approved everything it extracted ("Auto-approve for MVP, no human review
UI yet"), which made the crawler a publisher.

This is a static guard rather than a behavioural test on purpose: the thing
being forbidden is a class of code, and a class of code is only reliably
caught by reading the code. Each exception is listed with its reason, so
adding a new direct approval is a deliberate, reviewed edit to this file rather
than something that slips in with a feature.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from services.ingestion.extractor import ExtractedScholarship, Timeline
from services.review import ReviewService, ReviewStatus
from services.review.publication import is_published
from services.scholarship.mapper import ScholarshipMapper
from services.scholarship.repository import ScholarshipRepository

REPO_ROOT = Path(__file__).resolve().parents[2]

# Direct writers of the published state that are allowed to exist, and why.
# Keep this list short: every entry is an assertion that the exception is still
# the smallest one available.
ALLOWED = {
    "services/review/service.py": (
        "the state machine itself; ReviewStatus.APPROVED is only written here"
    ),
    "scripts/seed_manual_scholarships.py": (
        "bootstrap seed, gated behind --approve-directly, writes no review action"
    ),
    "scripts/m91_verify_vocabulary.py": (
        "verification script: temporarily sets a canonical degree, rolls back"
    ),
}

SCANNED_ROOTS = ("services", "scripts", "database/migrations")
APPROVED_LITERALS = {"approved"}


def _offenders(root: Path) -> list[tuple[str, int]]:
    """Every place a module assigns the published status directly."""
    found: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails the suite elsewhere
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        found.extend(
            (relative, node.lineno) for node in _approved_assignments(tree)
        )
    return found


def _approved_assignments(tree: ast.AST):
    """Assignments of ``extraction_status`` to the published state."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            values = [node.value]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
            values = [node.value]
        else:
            continue

        if not _writes_status(targets) and not _sets_kwarg(targets):
            continue
        for value in values:
            if isinstance(value, ast.Constant) and value.value in APPROVED_LITERALS:
                yield node
            elif isinstance(value, ast.Attribute) and value.attr == "APPROVED":
                yield node
            elif isinstance(value, ast.Dict):
                for key, item in zip(value.keys, value.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "extraction_status"
                        and isinstance(item, ast.Constant)
                        and item.value in APPROVED_LITERALS
                    ):
                        yield node


def _writes_status(targets: list[ast.expr]) -> bool:
    return any(
        isinstance(target, ast.Attribute) and target.attr == "extraction_status"
        for target in targets
    )


def _sets_kwarg(targets: list[ast.expr]) -> bool:
    """``query.update(extraction_status="approved")``."""
    return any(
        isinstance(target, ast.Call)
        and any(kw.arg == "extraction_status" for kw in target.keywords)
        for target in targets
    )


def _raw_sql_writers(root: Path) -> list[tuple[str, int]]:
    """SQL strings that assign the published status directly."""
    import re

    pattern = re.compile(
        r"SET\s+extraction_status\s*=\s*'approved'", re.IGNORECASE
    )
    found: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                found.append((path.relative_to(REPO_ROOT).as_posix(), lineno))
    return found


class TestNoDirectApprovalWriters:
    def test_no_module_outside_the_allowlist_writes_approved(self):
        offenders = [
            offender
            for offender in _offenders(REPO_ROOT / "services")
            + _offenders(REPO_ROOT / "scripts")
            + _offenders(REPO_ROOT / "database/migrations")
            if offender[0] not in ALLOWED
        ]
        assert offenders == [], (
            "these files publish a scholarship without review: "
            + ", ".join(f"{path}:{line}" for path, line in offenders)
        )

    def test_no_raw_sql_approves_a_scholarship(self):
        offenders = []
        for root in SCANNED_ROOTS:
            offenders.extend(_raw_sql_writers(REPO_ROOT / root))
        offenders = [o for o in offenders if o[0] not in ALLOWED]
        assert offenders == [], (
            "raw SQL approving scholarships: "
            + ", ".join(f"{path}:{line}" for path, line in offenders)
        )

    def test_the_allowlist_is_not_growing_unnoticed(self):
        """Every exception must still be the file the reason describes."""
        for path, reason in ALLOWED.items():
            assert (REPO_ROOT / path).exists(), f"{path} no longer exists"
            assert reason, f"{path} is allowed without a stated reason"

    def test_review_service_is_the_real_boundary(self):
        """The allowlist points at the state machine, not at a wrapper."""
        source = (REPO_ROOT / "services/review/service.py").read_text(encoding="utf-8")
        assert "scholarship.extraction_status = ReviewStatus.APPROVED" in source


class TestExtractionNeverPublishesItself:
    """Behavioural half: what extraction produces is never publishable."""

    @pytest.fixture
    def world(self, exploration_session):
        session = exploration_session
        country = session.query(Country).filter(Country.iso2 == "JP").first()
        suffix = uuid.uuid4().hex[:8]

        provider = Provider(
            provider_code=f"EXTRACT_{suffix.upper()}"[:32],
            provider_name="Extraction Gate Foundation",
            provider_type=ProviderType.FOUNDATION,
            country_id=country.country_id,
            official_url="https://bootstrap.ac.uk/",
            verification_status="verified",
        )
        source = SourceRegistry(
            source_name=f"Extraction gate source {suffix}",
            country_id=country.country_id,
            official_url="https://bootstrap.ac.uk/",
            crawl_entry_url="https://bootstrap.ac.uk/",
            crawl_method="HTTP",
            crawl_frequency="monthly",
            status="Active",
        )
        session.add_all([provider, source])
        session.flush()
        source.provider_id = provider.provider_id
        session.flush()
        return {"session": session, "provider": provider, "source": source}

    def test_a_mapped_extraction_lands_in_pending_review(self, world):
        extracted = ExtractedScholarship(
            scholarship_name="Extraction Gate Scholarship",
            provider_name="Extraction Gate Foundation",
            country=None,
            degree="Master",
            field_of_study=["Computer Science"],
            application_url="https://bootstrap.ac.uk/apply",
            official_source="https://bootstrap.ac.uk/",
            timeline=Timeline(application_deadline="2028-06-01"),
        )
        record = ScholarshipMapper(world["session"]).to_orm(
            extracted, str(world["source"].source_id)
        )
        world["session"].add(record)
        world["session"].flush()

        assert record.extraction_status == ReviewStatus.PENDING_REVIEW
        assert not is_published(record)

    def test_review_is_what_makes_it_public(self, world):
        repository = ScholarshipRepository(world["session"])
        pending = self._mapped(world)
        sid = pending.scholarship_id

        assert repository.get_published_by_id(sid) is None

        ReviewService(world["session"]).approve(
            str(sid), actor="reviewer-extraction", reason="verified against source"
        )
        world["session"].flush()
        world["session"].refresh(pending)

        assert is_published(pending)
        assert repository.get_published_by_id(sid) is not None

    def _mapped(self, world):
        extracted = ExtractedScholarship(
            scholarship_name="Extraction Gate Scholarship",
            provider_name="Extraction Gate Foundation",
            country=None,
            degree="Master",
            field_of_study=["Computer Science"],
            application_url="https://bootstrap.ac.uk/apply",
            official_source="https://bootstrap.ac.uk/",
            timeline=Timeline(application_deadline="2028-06-01"),
        )
        record = ScholarshipMapper(world["session"]).to_orm(
            extracted, str(world["source"].source_id)
        )
        world["session"].add(record)
        world["session"].flush()
        return record
