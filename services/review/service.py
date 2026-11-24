"""Review / curation domain — the publication boundary.

This service owns one thing: the ``extraction_status`` state machine. Every
other component reads that column but none of them may write it, so there is
exactly one place where "is this scholarship public?" is decided.

    PENDING_REVIEW ─┬─► APPROVED
                    ├─► REJECTED
                    └─► NEEDS_CORRECTION ─► PENDING_REVIEW

Each transition writes three things together, or none of them:

  1. the new ``extraction_status``
  2. a ``ScholarshipReviewAction`` row (who, when, why, what changed)
  3. a ``ScholarshipVersion`` row, when the action changed a value

That co-write is what makes the audit trail trustworthy. A change with no
version row, or a version with no audit row, is exactly the "silent
overwrite" the M9 brief prohibits.

Authentication is deliberately not implemented (out of scope for M9). The
service takes an explicit ``actor`` on every action so that adding auth
later means populating the actor from a request context, not restructuring
the calls.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models.scholarship import Scholarship
from database.models.scholarship_benefit import ScholarshipBenefit
from database.models.scholarship_candidate_revision import (
    CandidateStatus,
    ScholarshipCandidateRevision,
)
from database.models.scholarship_degree_level import ScholarshipDegreeLevel
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_review_action import (
    ReviewActionType,
    ReviewSource,
    ScholarshipReviewAction,
)
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.scholarship_version import ScholarshipVersion
from services.domain.vocabulary import UNMAPPED_QUALIFICATION_NOTE, InvalidVocabularyValue
from services.domain.vocabulary import validate as validate_controlled
from services.review.publication import PUBLISHED_STATE
from services.review.quality import (
    QualityReport,
    build_report,
    placeholder_source_host,
)

logger = logging.getLogger("polaris.review")

# An extraction the extractor itself judged weakly. Counted rather than
# hidden, because a pipeline that produces mostly low-confidence records is a
# pipeline a reviewer has to be warned about.
LOW_CONFIDENCE_THRESHOLD = 0.5


class ReviewStatus:
    """The publication state machine's vocabulary.

    Lowercase to match the existing ``extraction_status`` column. ``APPROVED``
    is the published state and is imported from `publication.py` rather than
    repeated here, so the state machine and every public read path are
    literally comparing against the same value.
    """

    PENDING_REVIEW = "pending_review"
    APPROVED = PUBLISHED_STATE
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"


class InvalidTransition(Exception):
    """Raised when a review action is not legal from the current state."""


class NotPublishable(Exception):
    """Raised when an approval would publish a record failing its gates."""


# Where a published value came from. Recorded on every field entry so
# "who decided this?" is answerable without replaying the audit trail.
#
#   machine_extracted  deterministic or LLM extraction, evidence = document id
#   human_review        a reviewer corrected it, evidence = the URL they used
#   reacquisition       observed upstream, not yet accepted by a human
#
# Normalization is deliberately NOT one of these. `"master's degree"` becoming
# `Master` is deterministic, not a decision, and conflating the two would claim
# a human verified something they never saw.
PROVENANCE_MACHINE = "machine_extracted"
PROVENANCE_HUMAN = "human_review"
PROVENANCE_REACQUISITION = "reacquisition"

# The extractor's provenance keys predate the column names it now writes.
_PROVENANCE_KEY_ALIASES = {"application_deadline": "deadline"}

# Bounded so a record corrected repeatedly cannot grow an unbounded JSON blob
# per field. Deeper history stays available in scholarship_review_action, which
# is append-only and never truncated.
_MAX_PREVIOUS_DEPTH = 5


def _provenance_key(existing: dict, field: str) -> str:
    """Which provenance key the currently published value belongs under.

    Only redirects when that key already exists. A record that stores the
    deadline under ``application_deadline`` must be updated in place: writing a
    second entry under ``deadline`` would leave the stale one describing a
    value that is no longer published, which is the drift this phase exists to
    remove.
    """
    alias = _PROVENANCE_KEY_ALIASES.get(field)
    return alias if alias and alias in existing else field


def _deepen_previous(entry: dict) -> dict:
    """Copy a prior provenance entry for nesting under ``previous``.

    A correction chain machine -> human A -> human B reads as::

        CURRENT:  origin=human_review, actor=B, previous=<A's entry>
                                     previous=<machine entry>

    The copy is shallow at the top and walked to the bottom, because the depth
    bound has to be applied where the chain actually ends rather than at the
    newest link.
    """
    nested = dict(entry)
    depth = 0
    node = nested
    while isinstance(node.get("previous"), dict):
        depth += 1
        if depth >= _MAX_PREVIOUS_DEPTH:
            node["previous"] = {
                "truncated": True,
                "history": "see scholarship_review_action",
            }
            break
        node = node["previous"]
    return nested


class InvalidFieldValue(InvalidTransition):
    """A controlled field was given a value outside its vocabulary.

    Distinct from `InvalidTransition` so the API can answer 422 (the request
    was well formed, the value is not) rather than 409 (the record is not in a
    state that allows this action). Both are 4xx; the distinction tells the
    reviewer whether to fix their input or reload the record.

    The cause is an `InvalidVocabularyValue` from `services.domain.vocabulary`,
    which carries the field, the refused value, the allowed set, and whether
    null is acceptable.
    """


class StaleCandidate(Exception):
    """Raised when a candidate was proposed against an out-of-date version.

    Raised instead of approving anyway. The record moved after the reviewer
    started looking at it, so applying the proposal would silently discard
    whatever changed in between — the failure mode M9.1 exists to remove.
    """


# State -> states reachable from it. REJECTED is terminal for the reviewer
# (re-open explicitly by setting PENDING_REVIEW through a correction), and
# APPROVED can be revoked, because publishing something wrong must always be
# reversible.
_ALLOWED: dict[str, set[str]] = {
    ReviewStatus.PENDING_REVIEW: {
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.NEEDS_CORRECTION,
    },
    ReviewStatus.NEEDS_CORRECTION: {
        ReviewStatus.PENDING_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
    },
    ReviewStatus.APPROVED: {
        ReviewStatus.PENDING_REVIEW,
        ReviewStatus.REJECTED,
    },
    ReviewStatus.REJECTED: {
        ReviewStatus.PENDING_REVIEW,
    },
}


@dataclass
class ReviewOutcome:
    """What a review action did, for the API to report back."""

    scholarship_id: str
    previous_state: str
    new_state: str
    action: str
    version_id: str | None = None
    field_changes: list[dict] = field(default_factory=list)
    quality: dict | None = None

    def to_dict(self) -> dict:
        return {
            "scholarship_id": self.scholarship_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "action": self.action,
            "version_id": self.version_id,
            "field_changes": self.field_changes,
            "quality_report": self.quality,
        }


def _coerce_uuid(value: Any) -> Any:
    """Accept a UUID as a string, refusing anything that is not one.

    Reviewers type ids as text and JSON round-trips them as strings; storing a
    string in a UUID column would fail at flush, long after the edit was
    reported as applied.
    """
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise InvalidFieldValue(f"not a valid id: {value!r}") from None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _enum_value(value):
    """Normalise a Python enum column to its string value."""
    return getattr(value, "value", value)


def _safe_attr(entity, relation: str, attribute: str):
    """Read a relationship attribute, tolerating detached or unloaded state.

    Review reads happen outside a session commit (a reviewer must be able to
    inspect a record without writing), so a lazy load can fail. Returning
    None degrades to a MISSING gate rather than raising mid-review.
    """
    try:
        related = getattr(entity, relation, None)
        return getattr(related, attribute, None) if related is not None else None
    except Exception:  # noqa: BLE001 — detached instance, or a lazy-load failure
        return None


class ReviewService:
    """The only writer of ``scholarship.extraction_status``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, scholarship_id: str) -> Scholarship | None:
        return (
            self.session.query(Scholarship)
            .filter(Scholarship.scholarship_id == scholarship_id)
            .first()
        )

    def list_for_review(
        self,
        *,
        state: str | None = ReviewStatus.PENDING_REVIEW,
        origin: str | None = None,
        country_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Scholarship], int]:
        """The review queue.

        ``state=None`` returns every record, which is what the metrics view
        needs in order to compute approval and rejection rates.
        """
        query = self.session.query(Scholarship)
        if state:
            query = query.filter(Scholarship.extraction_status == state)
        if origin:
            query = query.filter(Scholarship.provenance_origin == origin)
        if country_id:
            # The queue spans countries, so scoping is a reviewer need, not a
            # test convenience: nobody triages 130 countries at once.
            query = query.filter(Scholarship.country_id == uuid.UUID(str(country_id)))
        total = query.count()
        rows = (
            query.order_by(Scholarship.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return rows, total

    def history(self, scholarship_id: str) -> list[ScholarshipReviewAction]:
        return (
            self.session.query(ScholarshipReviewAction)
            .filter(ScholarshipReviewAction.scholarship_id == scholarship_id)
            .order_by(ScholarshipReviewAction.occurred_at.asc())
            .all()
        )

    def versions(self, scholarship_id: str) -> list[ScholarshipVersion]:
        return (
            self.session.query(ScholarshipVersion)
            .filter(ScholarshipVersion.scholarship_id == scholarship_id)
            .order_by(ScholarshipVersion.version_number.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # Candidate revisions (M9.1 Phase 2)
    #
    # A re-acquisition observes; it does not decide. Everything that would
    # change a published value arrives here as a proposal on this side of the
    # boundary, and only these methods can turn a proposal into published data.
    # ------------------------------------------------------------------

    def candidates(
        self,
        scholarship_id: str | None = None,
        *,
        status: str | None = CandidateStatus.PENDING,
    ) -> list[ScholarshipCandidateRevision]:
        """Proposed revisions, newest first. ``status=None`` returns all."""
        query = self.session.query(ScholarshipCandidateRevision)
        if scholarship_id:
            query = query.filter(
                ScholarshipCandidateRevision.scholarship_id == scholarship_id
            )
        if status:
            query = query.filter(ScholarshipCandidateRevision.status == status)
        return query.order_by(ScholarshipCandidateRevision.detected_at.desc()).all()

    def propose_candidate(
        self,
        scholarship: Scholarship,
        *,
        observed: dict[str, Any],
        actor: str,
        origin: str = "reacquisition",
        source_url: str | None = None,
        raw_document_id: str | None = None,
        reason: str | None = None,
    ) -> ScholarshipCandidateRevision | None:
        """Record observed values as a proposal. Publishes nothing.

        ``observed`` maps reviewable field names to the freshly seen value.
        Fields whose value already matches the published record are dropped
        rather than proposed, because a proposal that would change nothing is
        noise in a reviewer's queue.

        Returns ``None`` when nothing differs. A re-acquisition of an unchanged
        page is a healthy outcome, not a failure.

        The scholarship is locked here as well as at decision time: taking the
        lock at proposal time means the ``base_version_number`` recorded below
        is a value no concurrent writer can have moved past between the read
        and the write.
        """
        locked = self._lock_scholarship_by_id(scholarship.scholarship_id)

        changes = self._diff_against_published(locked, observed)
        if not changes:
            return None

        # One pending proposal per page. A second observation of the same URL
        # supersedes the first rather than queueing a duplicate, so a nightly
        # crawl cannot bury a reviewer in identical proposals.
        source_key = source_url or locked.official_page_url
        existing = (
            self.session.query(ScholarshipCandidateRevision)
            .filter(
                ScholarshipCandidateRevision.scholarship_id == locked.scholarship_id,
                ScholarshipCandidateRevision.source_url == source_key,
                ScholarshipCandidateRevision.status == CandidateStatus.PENDING,
            )
            .with_for_update()
            .one_or_none()
        )
        if existing is not None:
            existing.proposed_changes = _json_safe(changes)
            existing.field_provenance = self._candidate_provenance(
                changes, source_url, raw_document_id
            )
            existing.base_version_number = self._next_version_number(
                locked.scholarship_id
            ) - 1
            existing.detected_at = datetime.now(timezone.utc)
            self.session.flush()
            return existing

        candidate = ScholarshipCandidateRevision(
            scholarship_id=locked.scholarship_id,
            status=CandidateStatus.PENDING,
            source_url=source_key,
            origin=origin,
            raw_document_id=raw_document_id or None,
            detected_at=datetime.now(timezone.utc),
            proposed_changes=_json_safe(changes),
            field_provenance=self._candidate_provenance(
                changes, source_url, raw_document_id
            ),
            quality_snapshot=_json_safe(
                {"based_on_version": self._current_version_number(locked.scholarship_id)}
            ),
            base_version_number=self._current_version_number(locked.scholarship_id),
        )
        self.session.add(candidate)
        self.session.flush()

        # The audit trail records that a proposal exists, so "why is there a
        # pending candidate?" is answerable from the review history alone.
        # previous_state == new_state on purpose: the scholarship did not move.
        self._action_row(
            locked,
            ReviewActionType.CANDIDATE_PROPOSED,
            locked.extraction_status,
            locked.extraction_status,
            actor=actor,
            source=ReviewSource.SYSTEM,
            reason=reason or f"{origin} proposed {len(changes)} field change(s)",
            evidence_url=source_key,
            field_changes=changes,
            candidate_id=candidate.candidate_id,
        )
        return candidate

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        actor: str,
        reason: str,
        source: str = ReviewSource.ADMIN_API,
        evidence_url: str | None = None,
    ) -> ReviewOutcome:
        """Publish a candidate's proposed changes.

        Everything happens in one transaction under a row lock on the
        scholarship:

            lock → staleness check → apply changes → one version →
            one review action → candidate closed

        The record's ``extraction_status`` is never touched: it was already
        APPROVED and stays APPROVED. What changes is the data a reviewer has
        explicitly agreed is now correct.
        """
        if not (reason or "").strip():
            raise InvalidTransition("approving a candidate requires a reason")
        candidate = self._lock_candidate(candidate_id)
        if not candidate.is_actionable():
            raise InvalidTransition(
                f"candidate {candidate_id} is {candidate.status!r}, not pending"
            )

        scholarship = self._lock_scholarship(candidate.scholarship_id)

        # The record moved after this candidate was proposed. Publishing now
        # would silently discard that movement, so the reviewer is told to
        # look again instead.
        current_version = self._current_version_number(scholarship.scholarship_id)
        if (
            candidate.base_version_number is not None
            and current_version != candidate.base_version_number
        ):
            raise StaleCandidate(
                f"candidate {candidate_id} was proposed against version "
                f"{candidate.base_version_number} but the record is now at "
                f"version {current_version}; re-review before approving"
            )

        previous_state = scholarship.extraction_status

        # Same reason as `correct()`: refuse the whole proposal before any
        # field is applied, so a partially-applied approval is impossible.
        self._validate_controlled_changes(
            {
                change["field"]: change["new"]
                for change in (candidate.proposed_changes or [])
                if change.get("field") and "new" in change
            }
        )

        applied: list[dict] = []
        for change in candidate.proposed_changes or []:
            field = change.get("field")
            if not field or "new" not in change:
                continue
            entry = self._apply_field_change(
                scholarship, field, self._coerce_proposed(field, change["new"])
            )
            if entry is not None:
                applied.append(entry)

        if not applied:
            candidate.status = CandidateStatus.REJECTED
            candidate.decided_at = datetime.now(timezone.utc)
            candidate.decided_by = actor
            candidate.decision_reason = (
                f"no proposed field is applicable to this record: {reason}"
            )
            self.session.flush()
            raise InvalidTransition(
                f"candidate {candidate_id} proposed no applicable field changes"
            )

        # A corrected deadline invalidates the stored classification; leaving
        # it stale would keep an expired record published.
        self._reclassify_deadline(scholarship)

        report = self.evaluate_quality(scholarship)
        version = self.write_version(
            scholarship,
            summary=(
                f"candidate {candidate_id} approved by {actor}: {reason}"
            ),
            source_url=evidence_url or candidate.source_url,
            actor=actor,
            changes=applied,
        )

        candidate.status = CandidateStatus.APPROVED
        candidate.decided_at = datetime.now(timezone.utc)
        candidate.decided_by = actor
        candidate.decision_reason = reason

        provenance = self._record_correction_provenance(
            scholarship,
            applied,
            actor=actor,
            reason=reason,
            evidence_url=evidence_url or candidate.source_url,
            source=source,
            accepted_provenance=candidate.field_provenance or {},
        )
        scholarship.field_provenance = _json_safe(provenance)
        if candidate.source_url:
            # Re-verified: the reviewer confirmed this against the live page.
            scholarship.last_verified_at = datetime.now(timezone.utc)
        scholarship.reviewed_at = datetime.now(timezone.utc)
        scholarship.reviewed_by = actor
        scholarship.review_notes = reason
        scholarship.quality_report = report.to_dict()

        self._action_row(
            scholarship,
            ReviewActionType.CANDIDATE_APPROVED,
            previous_state,
            scholarship.extraction_status,
            actor=actor,
            source=source,
            reason=reason,
            evidence_url=evidence_url or candidate.source_url,
            field_changes=applied,
            version_id=version.version_id,
            candidate_id=candidate.candidate_id,
            quality_snapshot=report.to_dict(),
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous_state,
            new_state=scholarship.extraction_status,
            action=ReviewActionType.CANDIDATE_APPROVED,
            version_id=str(version.version_id),
            field_changes=applied,
            quality=report.to_dict(),
        )

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        actor: str,
        reason: str,
        source: str = ReviewSource.ADMIN_API,
    ) -> ReviewOutcome:
        """Close a proposal without touching the published record.

        The scholarship stays APPROVED and visible. Rejecting a candidate is
        not rejecting a scholarship: the opportunity remains published with the
        values it already had, and the reason the fresh observation was
        refused is kept on the audit trail.
        """
        if not (reason or "").strip():
            raise InvalidTransition("rejecting a candidate requires a reason")

        candidate = self._lock_candidate(candidate_id)
        if not candidate.is_actionable():
            raise InvalidTransition(
                f"candidate {candidate_id} is {candidate.status!r}, not pending"
            )

        scholarship = self._lock_scholarship(candidate.scholarship_id)
        previous_state = scholarship.extraction_status

        candidate.status = CandidateStatus.REJECTED
        candidate.decided_at = datetime.now(timezone.utc)
        candidate.decided_by = actor
        candidate.decision_reason = reason

        self._action_row(
            scholarship,
            ReviewActionType.CANDIDATE_REJECTED,
            previous_state,
            previous_state,
            actor=actor,
            source=source,
            reason=reason,
            evidence_url=candidate.source_url,
            field_changes=candidate.proposed_changes or [],
            candidate_id=candidate.candidate_id,
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous_state,
            new_state=previous_state,
            action=ReviewActionType.CANDIDATE_REJECTED,
            field_changes=list(candidate.proposed_changes or []),
        )

    def _record_correction_provenance(
        self,
        scholarship: Scholarship,
        applied: list[dict],
        *,
        actor: str,
        reason: str,
        evidence_url: str | None,
        source: str,
        accepted_provenance: dict | None = None,
        unmapped_qualification: dict[str, str] | None = None,
    ) -> dict:
        """Update provenance for every field a review action just changed.

    The invariant this maintains:

        field_provenance[field] describes the evidence for the value that is
        published *right now*.

    A published value and its provenance must move together. If they drift, the
    record claims a reviewer verified something the source never said — or,
    worse, that a machine extracted a value a human chose.

    History is preserved rather than overwritten: the prior entry is kept under
    ``previous``. Deepening the chain is what makes several successive
    corrections recoverable ("who set this before Bob did?") without
    introducing a second provenance system — the full prior values already live
    in ``scholarship_review_action.field_changes``.
        """
        existing = dict(scholarship.field_provenance or {})
        accepted = accepted_provenance or {}
        stamp = datetime.now(timezone.utc).isoformat()

        for change in applied:
            name = change.get("field")
            if not name:
                continue

            # Reuse the key the field already has. The extractor records the
            # deadline as ``deadline`` while the column is ``application_deadline``;
            # writing a second entry under the column name would strand the first
            # and leave the record describing one field twice.
            key = _provenance_key(existing, name)
            prior = existing.get(key) or {}

            # Evidence accepted from a candidate revision takes precedence over
            # plain defaults: it points at the document the change actually came
            # from, which is not the record's original extraction document.
            entry = dict(accepted.get(name) or {})
            accepted_document = entry.get("document_id")

            entry.update(
                {
                    "origin": PROVENANCE_HUMAN,
                    "actor": actor,
                    "corrected_at": stamp,
                    "review_source": source,
                    "reason": reason,
                    "current_value": _json_safe(change.get("new")),
                    "previous_value": _json_safe(change.get("previous")),
                    # Explicitly null rather than absent when the reviewer gave no
                    # URL. An absent key reads as "not recorded"; a null reads as
                    # "recorded, and there was none". Fabricating a document id
                    # here would be the single most damaging thing this code could
                    # do to the provenance chain. A document accepted with a
                    # candidate is kept, because it backs the value being
                    # published; otherwise the superseded document stays
                    # reachable under ``previous`` rather than being restated as
                    # if it still backed the current value.
                    "evidence_url": evidence_url,
                    "source_url": evidence_url or prior.get("source_url"),
                    "document_id": accepted_document,
                }
            )

            # The superseded entry is preserved whole — including its document —
            # so the value this one replaced stays recoverable from here.
            if prior:
                entry["previous"] = _deepen_previous(prior)

            # Evidence the reviewer supplied for a qualification Polaris has no
            # category for. Kept separate from the normalization vocabulary
            # (`source_value`): that records what the machine was told, this
            # records what a human read on the page and refused to map.
            term = (unmapped_qualification or {}).get(name)
            if term:
                entry["unmapped_qualification"] = term
                entry["note"] = UNMAPPED_QUALIFICATION_NOTE

            existing[key] = entry

        return existing

    @staticmethod
    def _check_unmapped_qualification(
        changes: dict, unmapped_qualification: dict[str, str] | None
    ) -> None:
        """Refuse unmapped-qualification evidence that contradicts the edit.

        The evidence describes a field the source filled with something Polaris
        cannot categorise, so the corrected value must be null. Any other value
        would put "the source said diploma" beside "the published value is
        Bachelor" and leave the record explaining two different things at once.

        Evidence for a field that is not being corrected is refused too: it has
        nowhere to land, and a reviewer who believed it was recorded would be
        wrong about their own edit.
        """
        for name in unmapped_qualification or {}:
            alias = _PROVENANCE_KEY_ALIASES.get(name)
            if name not in changes and alias not in changes:
                raise InvalidFieldValue(
                    f"unmapped_qualification evidence for {name!r} was given "
                    f"but {name!r} is not being corrected"
                )
            value = changes.get(name, changes.get(alias or ""))
            if value is not None:
                raise InvalidFieldValue(
                    f"unmapped_qualification evidence for {name!r} requires the "
                    f"field to be corrected to null, not {value!r}"
                )

    @staticmethod
    def _validate_controlled_changes(changes: dict) -> None:
        """Reject out-of-vocabulary values before anything is written.

        Free-text fields pass through untouched; only fields with a registered
        vocabulary are checked. Runs before the row is locked and before any
        field is applied, so a refused correction leaves nothing behind.
        """
        for name, value in dict(changes).items():
            target = "application_deadline" if name == "deadline" else name
            if target == "degree_levels":
                # A set is not a scalar, so the scalar validator cannot read
                # it; each member is checked against the same vocabulary.
                if not isinstance(value, (list, tuple)):
                    raise InvalidFieldValue(
                        "degree_levels must be a list of degree levels"
                    )
                for level in value:
                    try:
                        validate_controlled("degree", level)
                    except InvalidVocabularyValue as exc:
                        raise InvalidFieldValue(str(exc)) from exc
                continue
            try:
                validate_controlled(target, value)
            except InvalidVocabularyValue as exc:
                raise InvalidFieldValue(str(exc)) from exc

    def _lock_candidate(self, candidate_id) -> ScholarshipCandidateRevision:
        candidate = (
            self.session.query(ScholarshipCandidateRevision)
            .filter(ScholarshipCandidateRevision.candidate_id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
            .one_or_none()
        )
        if candidate is None:
            raise InvalidTransition(f"candidate {candidate_id} not found")
        return candidate

    def _lock_scholarship(self, scholarship_id) -> Scholarship:
        """Lock the canonical record and return its *authoritative* state.

        Every mutation funnels through here, so two concurrent approvals, or an
        approval racing a correction, serialise on one row instead of
        interleaving. The lock is taken BEFORE the state machine is consulted,
        which is the only ordering that is safe: read-then-check-then-lock lets
        two transactions both observe the same pre-transition state and both
        decide they are allowed to proceed.

        ``populate_existing=True`` is load-bearing. Without it SQLAlchemy
        returns the instance already sitting in the identity map and skips the
        SELECT entirely, so a stale in-memory copy would be used for the
        transition check even though the row was locked — the lock would be
        held and the decision made against pre-lock data.
        """
        scholarship = (
            self.session.query(Scholarship)
            .filter(Scholarship.scholarship_id == scholarship_id)
            .with_for_update()
            .execution_options(populate_existing=True)
            .one_or_none()
        )
        if scholarship is None:
            raise InvalidTransition(f"scholarship {scholarship_id} not found")
        return scholarship

    def _lock_scholarship_by_id(self, scholarship_id) -> Scholarship:
        """Accept a UUID or a string id.

        The public transition methods are called with string ids from the API
        and UUID objects from the pipeline; normalising here keeps every caller
        on the same locking path.
        """
        if not isinstance(scholarship_id, uuid.UUID):
            try:
                scholarship_id = uuid.UUID(str(scholarship_id))
            except (ValueError, AttributeError, TypeError):
                raise InvalidTransition(
                    f"scholarship {scholarship_id!r} is not a valid id"
                ) from None
        return self._lock_scholarship(scholarship_id)

    # Timeline columns stored as DATE. A candidate's proposed values come back
    # from JSONB as ISO strings, so they have to be parsed before they reach a
    # date column — assigning the string would make `classify_deadline` fail
    # comparing str to date.
    _DATE_PROPOSABLE_FIELDS = frozenset(
        {"application_deadline", "application_open", "interview_date", "result_date", "study_start"}
    )

    @classmethod
    def _coerce_proposed(cls, field: str, value: Any) -> Any:
        """Restore a proposed value to the type its column expects."""
        if field not in cls._DATE_PROPOSABLE_FIELDS or not isinstance(value, str):
            return value
        try:
            return date.fromisoformat(value)
        except ValueError:
            # An unparseable date is not applied as-is: keeping the string
            # would corrupt the column. The reviewer's approval is the moment
            # to notice, so it is refused rather than silently stored.
            raise InvalidTransition(
                f"candidate proposed an unparseable {field}: {value!r}"
            ) from None

    def _current_version_number(self, scholarship_id) -> int:
        current = (
            self.session.query(func.max(ScholarshipVersion.version_number))
            .filter(ScholarshipVersion.scholarship_id == scholarship_id)
            .scalar()
        )
        return int(current or 0)

    def _diff_against_published(
        self, scholarship: Scholarship, observed: dict[str, Any]
    ) -> list[dict]:
        """Reduce observed values to the ones that actually differ.

        Compared against the *published* value, never against a transient
        object: the question is whether the public record would change.
        """
        changes: list[dict] = []
        for name, new_value in observed.items():
            target = "application_deadline" if name == "deadline" else name
            if target not in self._PROPOSABLE_FIELDS:
                continue
            current = self._read_published_field(scholarship, target)
            if current == new_value:
                continue
            changes.append(
                {
                    "field": target,
                    "previous": _json_safe(current),
                    "new": _json_safe(new_value),
                }
            )
        return changes

    def _read_published_field(self, scholarship: Scholarship, name: str):
        """Read one currently-published value, tolerating a missing child row."""
        if name in self._TIMELINE_FIELDS:
            timeline = scholarship.timeline
            return getattr(timeline, name, None) if timeline is not None else None
        if name in self._REQUIREMENT_FIELDS:
            requirement = scholarship.requirement
            return getattr(requirement, name, None) if requirement is not None else None
        if name in self._BENEFIT_FIELDS:
            benefit = scholarship.benefit
            return getattr(benefit, name, None) if benefit is not None else None
        if name == "field_of_study":
            return list(scholarship.field_of_study or [])
        return getattr(scholarship, name, None)

    @staticmethod
    def _candidate_provenance(
        changes: list[dict], source_url: str | None, raw_document_id: str | None
    ) -> dict:
        """Evidence for each proposed value, at proposal time.

        Marked ``reacquisition`` rather than ``human_review``: nobody has
        looked at this yet. Approving rewrites the origin for the accepted
        fields so the published provenance never implies a human verified a
        value they never saw.
        """
        stamp = datetime.now(timezone.utc).isoformat()
        return {
            change["field"]: {
                "origin": PROVENANCE_REACQUISITION,
                "source_url": source_url,
                "document_id": raw_document_id,
                "detected_at": stamp,
            }
            for change in changes
        }

    def _reclassify_deadline(self, scholarship: Scholarship) -> None:
        """Recompute deadline_state after an accepted timeline change."""
        from services.scholarship.freshness import classify_deadline

        timeline = scholarship.timeline
        deadline = timeline.application_deadline if timeline else None
        scholarship.deadline_state = classify_deadline(deadline)

    # ------------------------------------------------------------------
    # Internal write helpers
    # ------------------------------------------------------------------

    # Fields a candidate may propose. Deliberately narrower than the full
    # editable set: identity (scholarship_name, provider, official_page_url,
    # application_url) is excluded because re-acquisition has no business
    # redefining what a record *is*, and the publication boundary depends on
    # identity being stable.
    _PROPOSABLE_FIELDS = frozenset(
        {
            "degree",
            "funding_type",
            "field_of_study",
            "application_deadline",
            "deadline",
            "application_open",
            "application_cycle",
            "minimum_gpa",
            "ielts_required",
            "minimum_ielts",
            "toefl_required",
            "minimum_toefl",
            "tuition_fee",
            "monthly_allowance",
            "accommodation",
            "health_insurance",
            "travel_ticket",
            "research_grant",
        }
    )

    def _next_version_number(self, scholarship_id) -> int:
        current = (
            self.session.query(func.max(ScholarshipVersion.version_number))
            .filter(ScholarshipVersion.scholarship_id == scholarship_id)
            .scalar()
        )
        return int(current or 0) + 1

    def write_version(
        self,
        scholarship: Scholarship,
        *,
        summary: str,
        source_url: str | None,
        actor: str,
        changes: list[dict] | None = None,
    ) -> ScholarshipVersion:
        """Append a version row. Never overwrites history.

        The caller is expected to already hold the row lock (every mutation
        method does), but the lock is re-affirmed here because this is the one
        place a version number is allocated. The re-lock deliberately omits
        ``populate_existing``: the caller has already mutated the in-memory
        instance, and refreshing it here would silently discard those pending
        changes. Re-issuing SELECT ... FOR UPDATE in the same transaction is
        harmless and makes the invariant hold for any future caller.
        """
        (
            self.session.query(Scholarship.scholarship_id)
            .filter(Scholarship.scholarship_id == scholarship.scholarship_id)
            .with_for_update()
            .one_or_none()
        )

        version = ScholarshipVersion(
            scholarship_id=scholarship.scholarship_id,
            version_number=self._next_version_number(scholarship.scholarship_id),
            changed_at=datetime.now(timezone.utc),
            source_url=source_url,
            change_summary=summary,
        )
        self.session.add(version)
        self.session.flush()
        if changes:
            logger.debug(
                "version %s for %s changed %d field(s) by %s",
                version.version_number, scholarship.scholarship_id, len(changes), actor,
            )
        return version

    def record_submission(
        self,
        scholarship: Scholarship,
        *,
        actor: str,
        quality_report: QualityReport | None = None,
        source: str = ReviewSource.SYSTEM,
        evidence_url: str | None = None,
    ) -> ScholarshipReviewAction:
        """Record that a record entered the review queue.

        Called by the pipeline on every extraction so that a record's arrival
        is auditable, not just its decision. Idempotent: a record already in
        the queue does not gain a second submission row.
        """
        previous = scholarship.extraction_status
        if previous == ReviewStatus.PENDING_REVIEW:
            return self._latest_action(scholarship.scholarship_id) or self._action_row(
                scholarship, ReviewActionType.SUBMITTED, previous, ReviewStatus.PENDING_REVIEW,
                actor=actor, source=source, evidence_url=evidence_url,
                quality_snapshot=quality_report.to_dict() if quality_report else None,
            )

        action = self._action_row(
            scholarship, ReviewActionType.SUBMITTED, previous, ReviewStatus.PENDING_REVIEW,
            actor=actor, source=source, evidence_url=evidence_url,
            quality_snapshot=quality_report.to_dict() if quality_report else None,
        )
        scholarship.extraction_status = ReviewStatus.PENDING_REVIEW
        scholarship.reviewed_at = None
        scholarship.reviewed_by = None
        return action

    def _latest_action(self, scholarship_id) -> ScholarshipReviewAction | None:
        return (
            self.session.query(ScholarshipReviewAction)
            .filter(ScholarshipReviewAction.scholarship_id == scholarship_id)
            .order_by(ScholarshipReviewAction.occurred_at.desc())
            .first()
        )

    def _action_row(
        self,
        scholarship: Scholarship,
        action: str,
        previous_state: str | None,
        new_state: str,
        *,
        actor: str,
        source: str,
        reason: str | None = None,
        evidence_url: str | None = None,
        field_changes: list[dict] | None = None,
        version_id=None,
        quality_snapshot: dict | None = None,
        candidate_id=None,
    ) -> ScholarshipReviewAction:
        row = ScholarshipReviewAction(
            scholarship_id=scholarship.scholarship_id,
            action=action,
            actor=actor,
            occurred_at=datetime.now(timezone.utc),
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            evidence_url=evidence_url,
            field_changes=_json_safe(field_changes or []),
            version_id=version_id,
            candidate_id=candidate_id,
            # The snapshot carries live values (dates, lists) straight off the
            # record, so it needs the same serialisation as field_changes.
            quality_snapshot=_json_safe(quality_snapshot) if quality_snapshot else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def _assert_transition(self, current: str, target: str) -> None:
        allowed = _ALLOWED.get(current or ReviewStatus.PENDING_REVIEW, set())
        if target not in allowed:
            raise InvalidTransition(
                f"cannot move scholarship from {current!r} to {target!r}; "
                f"allowed: {sorted(allowed) or 'none'}"
            )

    def approve(
        self,
        scholarship_id: str,
        *,
        actor: str,
        reason: str | None = None,
        source: str = ReviewSource.ADMIN_API,
        evidence_url: str | None = None,
        override_quality: bool = False,
        overridable_fields: tuple = (
            # Both spellings of the same fact: the quality report blocks on the
            # stored column name and on the gate's name, so a reviewer who may
            # override one could not override the other.
            "degree", "funding_type", "field_of_study", "deadline",
            "application_deadline",
            "application_open", "application_cycle", "minimum_gpa",
        ),
    ) -> ReviewOutcome:
        """Publish a scholarship.

        Refuses when the record's own quality report says it is not
        publishable. An override exists for one narrow case: a reviewer has
        read the official page, found the record genuinely correct, and the
        gate is blocking on a field that is legitimately absent (a
        merit-only award with no stated degree, say).

        Two categories are *never* overridable, because publishing them would
        break the provenance chain M9 depends on:

          identity         an unidentifiable record is not a scholarship
          official_source  an untraceable record cannot be trusted

        Overrides are recorded, never silent: the overridden fields and the
        reviewer's reason are stored on both the version and the audit row.
        """
        scholarship = self._lock_scholarship_by_id(scholarship_id)

        current = scholarship.extraction_status
        self._assert_transition(current, ReviewStatus.APPROVED)

        report = self.evaluate_quality(scholarship)
        if not report.publishable:
            blocking = report.blocking
            unoverridable = [b for b in blocking if b not in overridable_fields]
            if unoverridable or not override_quality:
                detail = ", ".join(blocking)
                hint = (
                    " — correct the record, or approve with override_quality and a reason"
                    if not unoverridable
                    else " — these can never be overridden"
                )
                raise NotPublishable(
                    f"cannot approve {scholarship_id}: {detail}{hint}"
                )
            if not (reason or "").strip():
                raise NotPublishable(
                    f"approving {scholarship_id} over {', '.join(blocking)} requires a reason"
                )

        changes: list[dict] = []
        overridden = report.blocking if not report.publishable else []
        version = self.write_version(
            scholarship,
            summary=(
                f"published by {actor}"
                + (f": {reason}" if reason else "")
                + (f" [quality override: {', '.join(overridden)}]" if overridden else "")
            ),
            source_url=evidence_url or scholarship.official_page_url,
            actor=actor,
            changes=changes,
        )

        previous = current
        scholarship.extraction_status = ReviewStatus.APPROVED
        scholarship.reviewed_at = datetime.now(timezone.utc)
        scholarship.reviewed_by = actor
        scholarship.review_notes = reason
        # The gate result is stored on the record too, so a later reviewer
        # sees what was known at publication time without replaying history.
        snapshot = report.to_dict()
        if overridden:
            snapshot["overridden_fields"] = overridden
        scholarship.quality_report = snapshot

        self._action_row(
            scholarship, ReviewActionType.APPROVED, previous, ReviewStatus.APPROVED,
            actor=actor, source=source, reason=reason, evidence_url=evidence_url,
            field_changes=changes, version_id=version.version_id,
            quality_snapshot=snapshot,
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous,
            new_state=ReviewStatus.APPROVED,
            action=ReviewActionType.APPROVED,
            version_id=str(version.version_id),
            field_changes=changes,
            quality=snapshot,
        )

    def reject(
        self,
        scholarship_id: str,
        *,
        actor: str,
        reason: str,
        source: str = ReviewSource.ADMIN_API,
        evidence_url: str | None = None,
    ) -> ReviewOutcome:
        """Remove a record from publication.

        A reason is mandatory: "rejected" without a reason is unauditable,
        and the M9 brief requires the decision to be explainable later.
        """
        if not (reason or "").strip():
            raise InvalidTransition("a rejection requires a reason")

        scholarship = self._lock_scholarship_by_id(scholarship_id)

        previous = scholarship.extraction_status
        self._assert_transition(previous, ReviewStatus.REJECTED)

        version = self.write_version(
            scholarship,
            summary=f"rejected by {actor}: {reason}",
            source_url=evidence_url or scholarship.official_page_url,
            actor=actor,
        )
        scholarship.extraction_status = ReviewStatus.REJECTED
        scholarship.reviewed_at = datetime.now(timezone.utc)
        scholarship.reviewed_by = actor
        scholarship.review_notes = reason

        self._action_row(
            scholarship, ReviewActionType.REJECTED, previous, ReviewStatus.REJECTED,
            actor=actor, source=source, reason=reason, evidence_url=evidence_url,
            version_id=version.version_id,
            quality_snapshot=(scholarship.quality_report or None),
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous,
            new_state=ReviewStatus.REJECTED,
            action=ReviewActionType.REJECTED,
            version_id=str(version.version_id),
        )

    def request_correction(
        self,
        scholarship_id: str,
        *,
        actor: str,
        reason: str,
        fields: list[str] | None = None,
        source: str = ReviewSource.ADMIN_API,
        evidence_url: str | None = None,
    ) -> ReviewOutcome:
        """Ask for a change without discarding the record.

        Keeps the record out of publication while a correction is prepared,
        which is different from rejection: the opportunity may still be
        real, only its data is wrong.
        """
        if not (reason or "").strip():
            raise InvalidTransition("requesting a correction requires a reason")

        scholarship = self._lock_scholarship_by_id(scholarship_id)

        previous = scholarship.extraction_status
        self._assert_transition(previous, ReviewStatus.NEEDS_CORRECTION)

        scholarship.extraction_status = ReviewStatus.NEEDS_CORRECTION
        scholarship.reviewed_at = datetime.now(timezone.utc)
        scholarship.reviewed_by = actor
        scholarship.review_notes = reason

        detail = {"requested_fields": fields or []}
        self._action_row(
            scholarship, ReviewActionType.NEEDS_CORRECTION, previous,
            ReviewStatus.NEEDS_CORRECTION,
            actor=actor, source=source, reason=reason, field_changes=detail,
            evidence_url=evidence_url,
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous,
            new_state=ReviewStatus.NEEDS_CORRECTION,
            action=ReviewActionType.NEEDS_CORRECTION,
            field_changes=[detail],
        )

    def correct(
        self,
        scholarship_id: str,
        *,
        actor: str,
        changes: dict[str, Any],
        reason: str,
        source: str = ReviewSource.ADMIN_API,
        evidence_url: str | None = None,
        requeue: bool = True,
        unmapped_qualification: dict[str, str] | None = None,
    ) -> ReviewOutcome:
        """Apply reviewer edits, recording every previous value.

        Each edit produces one ``field_changes`` entry with the old and new
        value, and one version row summarising the correction. Nothing is
        overwritten silently.

        ``unmapped_qualification`` maps a corrected field to the wording the
        source used for a qualification Polaris has no category for, e.g.
        ``{"degree": "diploma"}``. It exists so a reviewer can empty a
        controlled field *with the evidence attached* — "the page says diploma
        and we have no level for that" — instead of leaving a bare NULL that a
        later reader mistakes for a failed extraction. Requires the field to be
        corrected to null: evidence of an unmappable value on a field that now
        holds a canonical value would be a provenance entry contradicting the
        published one.
        """
        if not changes:
            raise InvalidTransition("a correction requires at least one field change")
        if not (reason or "").strip():
            raise InvalidTransition("a correction requires a reason")
        self._check_unmapped_qualification(changes, unmapped_qualification)

        # Validate the whole change set before applying any of it. Applying
        # field-by-field and failing on the third would leave the first two
        # mutated in the session — a reviewer fixing a typo would see their
        # record half-edited when the error came back.
        self._validate_controlled_changes(changes)

        scholarship = self._lock_scholarship_by_id(scholarship_id)

        previous_state = scholarship.extraction_status
        applied: list[dict] = []
        applied_fields: set[str] = set()

        for name, new_value in changes.items():
            entry = self._apply_field_change(scholarship, name, new_value)
            if entry is None:
                continue
            applied.append(entry)
            applied_fields.add(entry["field"])

        if not applied:
            # "not an editable field" must mean exactly that. A field this
            # service *does* edit but whose value already matched is a no-op,
            # and reporting it as a typo sends the reviewer looking for a
            # spelling mistake that is not there.
            editable = self._editable_field_names()
            unknown = sorted(set(changes) - editable)
            if unknown:
                # Naming the field is the whole point: a typo must not look
                # like a silent success.
                raise InvalidTransition(
                    "not an editable field: " + ", ".join(unknown)
                )
            raise InvalidTransition(
                "no requested field actually changed: " + ", ".join(sorted(changes))
            )

        version = self.write_version(
            scholarship,
            summary=f"corrected by {actor}: {reason}",
            source_url=evidence_url or scholarship.official_page_url,
            actor=actor,
            changes=applied,
        )

        # Provenance follows the value. Without this the record would publish a
        # reviewer-corrected field while still claiming the extractor produced
        # it — which is the exact failure this phase closes.
        scholarship.field_provenance = _json_safe(
            self._record_correction_provenance(
                scholarship,
                applied,
                actor=actor,
                reason=reason,
                evidence_url=evidence_url,
                source=source,
                unmapped_qualification=unmapped_qualification,
            )
        )

        # A reviewer correcting the country IS the confirmation the quality
        # gate waits for when the extractor only inferred the country from
        # the source. Clear the inference flag, or the gate would keep
        # blocking a record a human has now vouched for.
        if "country_id" in applied_fields and isinstance(
            scholarship.quality_report, dict
        ):
            updated_report = dict(scholarship.quality_report)
            updated_report["country_inferred_from_source"] = False
            scholarship.quality_report = updated_report

        target = ReviewStatus.PENDING_REVIEW if requeue else previous_state
        if requeue and target != previous_state:
            # Re-queueing is a transition, so it is checked like one.
            self._assert_transition(previous_state, ReviewStatus.PENDING_REVIEW)

        scholarship.extraction_status = target
        scholarship.reviewed_at = datetime.now(timezone.utc)
        scholarship.reviewed_by = actor
        scholarship.review_notes = reason
        if evidence_url:
            # A correction carrying an evidence URL is a verification: the
            # reviewer opened that page and changed the record to match it.
            # Leaving last_verified_at untouched here is what made the V0.1
            # report show the field empty on records that had just been
            # checked against a live source. A correction with no evidence
            # URL is a desk edit and deliberately does not claim otherwise.
            scholarship.last_verified_at = datetime.now(timezone.utc)

        self._action_row(
            scholarship, ReviewActionType.CORRECTED, previous_state, target,
            actor=actor, source=source, reason=reason, evidence_url=evidence_url,
            field_changes=applied, version_id=version.version_id,
        )
        return ReviewOutcome(
            scholarship_id=str(scholarship.scholarship_id),
            previous_state=previous_state,
            new_state=target,
            action=ReviewActionType.CORRECTED,
            version_id=str(version.version_id),
            field_changes=applied,
        )

    # ------------------------------------------------------------------
    # Field editing
    # ------------------------------------------------------------------

    _TIMELINE_FIELDS = {
        "application_open", "application_deadline", "deadline",
        "application_cycle", "interview_date", "result_date", "study_start",
    }
    _REQUIREMENT_FIELDS = {
        "minimum_gpa", "ielts_required", "minimum_ielts", "toefl_required",
        "minimum_toefl", "work_experience", "research_experience", "publication",
    }
    _BENEFIT_FIELDS = {
        "tuition_fee", "monthly_allowance", "accommodation",
        "health_insurance", "travel_ticket", "research_grant",
    }

    def _provider_exists(self, provider_id) -> bool:
        """Whether the proposal names a provider row that actually exists."""
        from database.models.provider import Provider

        value = provider_id if isinstance(provider_id, uuid.UUID) else None
        if value is None:
            try:
                value = uuid.UUID(str(provider_id))
            except (ValueError, AttributeError, TypeError):
                return False
        return (
            self.session.query(Provider.provider_id)
            .filter(Provider.provider_id == value)
            .first()
            is not None
        )

    def _country_exists(self, country_id) -> bool:
        """Whether a correction names a country row that actually exists."""
        from database.models.country import Country

        value = country_id if isinstance(country_id, uuid.UUID) else None
        if value is None:
            try:
                value = uuid.UUID(str(country_id))
            except (ValueError, AttributeError, TypeError):
                return False
        return (
            self.session.query(Country.country_id)
            .filter(Country.country_id == value)
            .first()
            is not None
        )

    @staticmethod
    def _child(scholarship: Scholarship, attr: str, model):
        """Return the 1:1 child row, creating it on first write."""
        existing = getattr(scholarship, attr)
        if existing is None:
            existing = model(scholarship_id=scholarship.scholarship_id)
            setattr(scholarship, attr, existing)
        return existing

    def _editable_field_names(self) -> set[str]:
        """Every field name `correct()` accepts."""
        return {
            "scholarship_name",
            "provider_id",
            "country_id",
            "degree",
            "degree_levels",
            "funding_type",
            "official_page_url",
            "application_url",
            "field_of_study",
            *self._TIMELINE_FIELDS,
            *self._REQUIREMENT_FIELDS,
            *self._BENEFIT_FIELDS,
        }

    def _apply_field_change(self, scholarship: Scholarship, name: str, value: Any):
        """Set one field, returning {field, previous, new} or None if unknown."""
        target_name = "application_deadline" if name == "deadline" else name

        # Controlled vocabulary is checked before anything is read or written.
        # This is the publication boundary's last line of defence: a reviewer
        # typing degree="Polytechnic" gets a deterministic refusal naming the
        # allowed values, rather than a record that no matching profile can
        # ever match. Validated first so the refusal happens before any partial
        # mutation of the record.
        try:
            validate_controlled(target_name, value)
        except InvalidVocabularyValue as exc:
            raise InvalidFieldValue(str(exc)) from exc

        # The official link is the record's trust anchor, and this method is the
        # one place both `correct()` and `approve_candidate()` write it. The
        # quality gate refuses a placeholder source at approval time, but a
        # correction that keeps an already-published record published
        # (`requeue=False`) never reaches that gate — so the value itself is
        # refused here, before it can become the source of a live record.
        if target_name in ("official_page_url", "application_url"):
            placeholder_host = placeholder_source_host(value)
            if placeholder_host:
                raise InvalidFieldValue(
                    f"{target_name} {value!r} uses a placeholder host "
                    f"({placeholder_host}); a reserved test name cannot be a "
                    "provider's page"
                )

        child = None
        if target_name == "scholarship_name":
            previous = scholarship.scholarship_name
        elif target_name == "provider_id":
            # Re-pointing a record at another provider is curation, not
            # identity resolution: it changes the provider name the public API
            # renders. It is allowed here, through the review workflow, so it
            # gets a version, an audit action and current provenance — and it
            # is deliberately NOT in `_PROPOSABLE_FIELDS`, because Phase 2
            # decided identity must not move on an automated observation.
            previous = scholarship.provider_id
            if value is not None and not self._provider_exists(value):
                # A reference to a provider that is not there would fail the
                # FK at flush time, long after the reviewer pressed approve.
                raise InvalidTransition(
                    f"cannot point a scholarship at provider {value!r}: "
                    "no such provider"
                )
        elif target_name == "country_id":
            # Same curation shape as provider_id. Country had no correction
            # path at all, which mattered once the quality gate began
            # treating an extractor-inferred country as unconfirmed: a
            # blocked record a reviewer cannot fix is a dead end, so the
            # confirmation path and the gate landed together.
            previous = scholarship.country_id
            if value is not None and not self._country_exists(value):
                raise InvalidTransition(
                    f"cannot point a scholarship at country {value!r}: "
                    "no such country"
                )
        elif target_name == "degree_levels":
            previous = sorted(row.degree for row in (scholarship.degree_levels or []))
        elif target_name in ("degree", "funding_type", "official_page_url", "application_url"):
            previous = getattr(scholarship, target_name, None)
        elif target_name == "field_of_study":
            previous = list(scholarship.field_of_study or [])
        elif target_name in self._TIMELINE_FIELDS:
            # A reviewer correcting a deadline on a record that never had a
            # timeline row must be able to supply one, otherwise the fields
            # that matter most are the ones a thin extraction cannot create.
            child = self._child(scholarship, "timeline", ScholarshipTimeline)
            previous = getattr(child, target_name, None)
        elif target_name in self._REQUIREMENT_FIELDS:
            child = self._child(scholarship, "requirement", ScholarshipRequirement)
            previous = getattr(child, target_name, None)
        elif target_name in self._BENEFIT_FIELDS:
            child = self._child(scholarship, "benefit", ScholarshipBenefit)
            previous = getattr(child, target_name, None)
        else:
            return None

        # One apparent no-op is a real reviewer act: confirming a country
        # the extractor only inferred. The value does not change, but the
        # record's epistemic state does — a human has now vouched for it —
        # so it is recorded as a change (and correct() clears the inference
        # flag) instead of being dismissed as "no change". Compared after
        # UUID coercion, because reviewers pass ids as strings.
        if (
            target_name == "country_id"
            and _coerce_uuid(value) == previous
            and isinstance(scholarship.quality_report, dict)
            and scholarship.quality_report.get("country_inferred_from_source")
        ):
            return {
                "field": target_name,
                "previous": _json_safe(previous),
                "new": _json_safe(value),
                "confirmed_inferred_country": True,
            }

        if previous == value:
            return None

        if target_name == "scholarship_name":
            scholarship.scholarship_name = value
        elif target_name == "provider_id":
            scholarship.provider_id = _coerce_uuid(value)
        elif target_name == "country_id":
            scholarship.country_id = _coerce_uuid(value)
        elif target_name in ("degree", "funding_type", "official_page_url", "application_url"):
            setattr(scholarship, target_name, value)
        elif target_name == "field_of_study":
            scholarship.field_of_study = list(value or [])
        elif target_name == "degree_levels":
            # Replace the set wholesale. A reviewer stating the levels is
            # stating the whole fact, and a merge would leave a level the
            # reviewer just removed.
            wanted = list(dict.fromkeys(value or []))
            scholarship.degree_levels = [
                row for row in (scholarship.degree_levels or []) if row.degree in wanted
            ] + [
                ScholarshipDegreeLevel(degree=level)
                for level in wanted
                if level not in {row.degree for row in (scholarship.degree_levels or [])}
            ]
        else:
            setattr(child, target_name, value)

        return {
            "field": target_name,
            "previous": _json_safe(previous),
            "new": _json_safe(value),
        }

    # ------------------------------------------------------------------
    # Quality evaluation
    # ------------------------------------------------------------------

    def evaluate_quality(self, scholarship: Scholarship) -> QualityReport:
        """Re-run the publication gates against a stored record.

        Read-only: evaluating never mutates. The stored ``quality_report``
        from extraction time is *not* reused, because the record may have
        been corrected since and the reviewer must see current truth.
        """
        provider_name = _safe_attr(scholarship, "provider", "provider_name")
        country_name = _safe_attr(scholarship, "country", "name")

        timeline = scholarship.timeline
        stored = scholarship.quality_report if isinstance(scholarship.quality_report, dict) else {}

        return build_report(
            scholarship_name=scholarship.scholarship_name,
            name_verdict=stored.get("name_verdict"),
            provider_name=provider_name,
            country_name=country_name,
            country_inferred=bool(stored.get("country_inferred_from_source")),
            official_page_url=scholarship.official_page_url,
            degree=scholarship.degree,
            degree_levels=[row.degree for row in (scholarship.degree_levels or [])],
            funding_type=scholarship.funding_type,
            field_of_study=scholarship.field_of_study,
            deadline_present=timeline is not None,
            application_deadline=(timeline.application_deadline if timeline else None),
            application_open=(timeline.application_open if timeline else None),
            application_cycle=(timeline.application_cycle if timeline else None),
            requirement=scholarship.requirement,
            benefit=scholarship.benefit,
            conflicts=scholarship.conflicts,
        )

    # ------------------------------------------------------------------
    # Reviewer packet
    # ------------------------------------------------------------------

    def review_packet(self, scholarship_id: str) -> dict:
        """Everything a reviewer needs for one record, in one call.

        Assembled here rather than in the router so the review contract is
        testable without HTTP, and so a future reviewer UI consumes the same
        shape the API serves.
        """
        from database.models.raw_document import RawDocument

        scholarship = self.get(scholarship_id)
        if scholarship is None:
            return None

        def read(entity, attribute, default=None):
            return getattr(entity, attribute, default) if entity is not None else default

        provider = scholarship.provider
        country = scholarship.country
        source = scholarship.source
        requirement = scholarship.requirement
        benefit = scholarship.benefit
        timeline = scholarship.timeline

        # Documents are the raw provenance behind every value on the record,
        # so the reviewer never has to query tables by hand to verify a field.
        document_ids: set[str] = set()
        for evidence in (scholarship.field_provenance or {}).values():
            if isinstance(evidence, dict):
                for key in ("document_id", "target_document_id"):
                    if evidence.get(key):
                        document_ids.add(str(evidence[key]))
                for nested in evidence.values():
                    if isinstance(nested, dict) and nested.get("document_id"):
                        document_ids.add(str(nested["document_id"]))
        for candidate in self.candidates(scholarship_id):
            if candidate.raw_document_id:
                document_ids.add(str(candidate.raw_document_id))
            provenance = candidate.field_provenance or {}
            document_ids.update(str(value) for value in provenance.get("evidence_document_ids", []))
        from sqlalchemy import or_

        source_is_aggregator = bool(source and source.page_type == "aggregator")
        document_filter = (
            RawDocument.document_id.in_([])
            if source_is_aggregator
            else RawDocument.source_id == scholarship.source_id
        )
        if document_ids:
            from uuid import UUID

            valid_ids = []
            for value in document_ids:
                try:
                    valid_ids.append(UUID(value))
                except ValueError:
                    continue
            if valid_ids:
                document_filter = or_(document_filter, RawDocument.document_id.in_(valid_ids))
        query = self.session.query(RawDocument).filter(document_filter)
        documents = query.order_by(RawDocument.fetched_at.desc()).limit(20).all()

        return {
            "scholarship_id": str(scholarship.scholarship_id),
            "extraction_status": scholarship.extraction_status,
            "identity": {
                "scholarship_name": scholarship.scholarship_name,
                "provider_name": read(provider, "provider_name"),
                "provider_type": _enum_value(read(provider, "provider_type")),
                "country": read(country, "name"),
                "university": read(scholarship.university, "name"),
                "official_url": scholarship.official_page_url,
                "application_url": scholarship.application_url,
                "source_id": str(scholarship.source_id),
                "source_name": read(source, "source_name"),
                "source_official_url": read(source, "official_url"),
                "source_verification_state": read(source, "verification_state"),
            },
            "eligibility": {
                "degree": scholarship.degree,
                "funding_type": scholarship.funding_type,
                "field_of_study": list(scholarship.field_of_study or []),
                "minimum_gpa": read(requirement, "minimum_gpa"),
                "ielts_required": read(requirement, "ielts_required"),
                "minimum_ielts": read(requirement, "minimum_ielts"),
                "toefl_required": read(requirement, "toefl_required"),
                "minimum_toefl": read(requirement, "minimum_toefl"),
                "work_experience": read(requirement, "work_experience"),
                "research_experience": read(requirement, "research_experience"),
                "publication": read(requirement, "publication"),
            },
            "funding": {
                "tuition_fee": read(benefit, "tuition_fee"),
                "monthly_allowance": read(benefit, "monthly_allowance"),
                "accommodation": read(benefit, "accommodation"),
                "health_insurance": read(benefit, "health_insurance"),
                "travel_ticket": read(benefit, "travel_ticket"),
                "research_grant": read(benefit, "research_grant"),
            },
            "timeline": {
                "application_open": read(timeline, "application_open"),
                "application_deadline": read(timeline, "application_deadline"),
                "application_cycle": read(timeline, "application_cycle"),
                "interview_date": read(timeline, "interview_date"),
                "result_date": read(timeline, "result_date"),
                "study_start": read(timeline, "study_start"),
            },
            # Evaluated live rather than read from the stored report: the
            # reviewer must see current truth, not what was true at extraction.
            "quality": self.evaluate_quality(scholarship).to_dict(),
            "provenance_origin": scholarship.provenance_origin,
            "extraction_confidence": scholarship.extraction_confidence,
            "conflicts": _json_safe(scholarship.conflicts or []),
            "field_provenance": _json_safe(scholarship.field_provenance or {}),
            "source_documents": [
                {
                    "document_id": str(doc.document_id),
                    "source_url": doc.source_url,
                    "fetched_at": doc.fetched_at,
                    "status_code": doc.status_code,
                    "content_type": doc.content_type,
                    "processing_status": doc.processing_status,
                }
                for doc in documents
            ],
            "history": [
                {
                    "review_action_id": str(a.review_action_id),
                    "action": a.action,
                    "actor": a.actor,
                    "occurred_at": a.occurred_at,
                    "previous_state": a.previous_state,
                    "new_state": a.new_state,
                    "reason": a.reason,
                    "field_changes": a.field_changes or [],
                    "evidence_url": a.evidence_url,
                    "version_id": str(a.version_id) if a.version_id else None,
                }
                for a in self.history(scholarship_id)
            ],
            "versions": [
                {
                    "version_id": str(v.version_id),
                    "version_number": v.version_number,
                    "changed_at": v.changed_at,
                    "source_url": v.source_url,
                    "change_summary": v.change_summary,
                }
                for v in self.versions(scholarship_id)
            ],
            # Proposals are shown next to the published values so a reviewer
            # sees "here is what changed upstream" without a second query.
            "pending_candidates": [
                {
                    "candidate_id": str(c.candidate_id),
                    "status": c.status,
                    "origin": c.origin,
                    "source_url": c.source_url,
                    "raw_document_id": (
                        str(c.raw_document_id) if c.raw_document_id else None
                    ),
                    "detected_at": c.detected_at,
                    "base_version_number": c.base_version_number,
                    "proposed_changes": c.proposed_changes or [],
                    "field_provenance": _json_safe(c.field_provenance or {}),
                }
                for c in self.candidates(scholarship_id)
            ],
            "reviewed_at": scholarship.reviewed_at,
            "reviewed_by": scholarship.reviewed_by,
            "review_notes": scholarship.review_notes,
        }

    def aggregator_candidates(self, *, limit: int = 50, state: str | None = "pending_review") -> list[dict]:
        """Return discovery observations that have not become Scholarship rows.

        The existing SourceRegistry JSON checkpoint is the queue store, so this
        read path needs neither country context nor a new persistence model.
        """
        from database.models.source_registry import SourceRegistry

        sources = (
            self.session.query(SourceRegistry)
            .filter(SourceRegistry.page_type == "aggregator")
            .order_by(SourceRegistry.source_name.asc())
            .all()
        )
        results = []
        for source in sources:
            if (source.discovered_via or {}).get("role") != "aggregator":
                continue
            for item in reversed(source.scholarship_page_urls or []):
                if state not in (None, "all") and item.get("state") != state:
                    continue
                from database.models.raw_document import RawDocument

                evidence_ids = [
                    item.get("article_document_id"),
                    item.get("official_document_id"),
                ]
                evidence_ids = [value for value in evidence_ids if value]
                evidence_documents = (
                    self.session.query(RawDocument)
                    .filter(RawDocument.document_id.in_(evidence_ids))
                    .order_by(RawDocument.fetched_at.asc())
                    .all()
                    if evidence_ids else []
                )
                results.append({
                    **item,
                    "aggregator_source_id": str(source.source_id),
                    "aggregator_name": source.source_name,
                    "source_verification_state": source.verification_state,
                    "source_documents": [
                        {
                            "document_id": str(document.document_id),
                            "source_url": document.source_url,
                            "fetched_at": document.fetched_at,
                            "status_code": document.status_code,
                            "content_type": document.content_type,
                        }
                        for document in evidence_documents
                    ],
                })
                if len(results) >= limit:
                    return results
        return results

    def queue_summary(self, row: Scholarship) -> dict:
        """One triage row: identity plus what would block publication.

        Gates are only re-evaluated when the record looks blocked, because
        evaluating every queue row would cost a relationship load per record.
        """
        summary = {
            "scholarship_id": str(row.scholarship_id),
            "scholarship_name": row.scholarship_name,
            "provider_name": _safe_attr(row, "provider", "provider_name"),
            "country": _safe_attr(row, "country", "name"),
            "official_url": row.official_page_url,
            "extraction_status": row.extraction_status,
            "provenance_origin": row.provenance_origin,
            "extraction_confidence": row.extraction_confidence,
            "created_at": row.created_at,
            "reviewed_at": row.reviewed_at,
            "reviewed_by": row.reviewed_by,
            "blocking_fields": [],
            "conflicting_fields": [],
        }
        # The extractor's own verdict is already stored, so the common case
        # costs nothing extra to display.
        stored = row.quality_report if isinstance(row.quality_report, dict) else {}
        if stored.get("blocking"):
            summary["blocking_fields"] = list(stored["blocking"])
            summary["conflicting_fields"] = list(stored.get("conflicting") or [])
        return summary

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self, *, country_id: str | None = None) -> dict:
        """Curation metrics, split by provenance origin.

        The split is the point. A single ``approved`` count cannot distinguish
        a reviewer approving what exploration discovered from a seed script
        inserting rows that were already correct, which is exactly the
        distinction Phase 13 exists to keep honest.
        """
        scoped = self.session.query(Scholarship)
        if country_id:
            scoped = scoped.filter(Scholarship.country_id == uuid.UUID(str(country_id)))

        by_state = {
            state: count
            for state, count in scoped.with_entities(
                Scholarship.extraction_status, func.count(Scholarship.scholarship_id)
            ).group_by(Scholarship.extraction_status).all()
        }
        by_origin = {
            (origin or "unknown"): count
            for origin, count in scoped.with_entities(
                Scholarship.provenance_origin, func.count(Scholarship.scholarship_id)
            ).group_by(Scholarship.provenance_origin).all()
        }

        approved = by_state.get(ReviewStatus.APPROVED, 0)
        rejected = by_state.get(ReviewStatus.REJECTED, 0)
        decided = approved + rejected

        with_conflicts = (
            scoped.filter(Scholarship.conflicts.isnot(None))
            .with_entities(func.count(Scholarship.scholarship_id))
            .scalar()
            or 0
        )
        low_confidence = (
            scoped.filter(
                Scholarship.extraction_confidence.isnot(None),
                Scholarship.extraction_confidence < LOW_CONFIDENCE_THRESHOLD,
            )
            .with_entities(func.count(Scholarship.scholarship_id))
            .scalar()
            or 0
        )

        pending = by_state.get(ReviewStatus.PENDING_REVIEW, 0)
        needs_correction = by_state.get(ReviewStatus.NEEDS_CORRECTION, 0)
        return {
            "total": sum(by_state.values()),
            "by_state": by_state,
            "by_origin": by_origin,
            "pending_review": pending,
            "approved": approved,
            "rejected": rejected,
            "needs_correction": needs_correction,
            # Undecided counts anything still in the queue, so it can never be
            # confused with a rejection rate computed over the wrong base.
            "undecided": pending + needs_correction,
            "approval_rate": round(approved / decided, 4) if decided else None,
            "rejection_rate": round(rejected / decided, 4) if decided else None,
            "records_with_conflicts": with_conflicts,
            "low_confidence_extractions": low_confidence,
        }
