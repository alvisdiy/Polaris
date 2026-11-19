"""Apply a reviewed quarantine manifest through ReviewService — dry-run by default.

Catalogue Trust Sprint, Task 2. The manifest at
``docs/audit/2026-10-15_quarantine_manifest.json`` records what a reviewer
believes should leave the public catalogue and why. This script is the only
thing that acts on it, and it acts only through ``ReviewService.reject`` — the
same state machine the admin API uses — so every applied record keeps its
version row, its audit row and its provenance untouched.

Safety properties, in the order they are enforced:

1. **Dry-run unless told otherwise.** ``--execute`` is opt-in; without it the
   script only reads and prints the plan. A bare invocation cannot change a row.
2. **The manifest is validated before a record is touched.** A malformed entry
   aborts with exit 2, rather than half-applying a plan.
3. **Preflight runs over every entry first, then nothing is applied if any
   entry is in an unexpected state.** The record's current status must equal
   the ``current_status`` recorded in the manifest. The one other status that is
   accepted is the action's own outcome (``rejected`` for a ``reject``), which
   is how a re-run stays idempotent instead of failing or double-writing.
4. **Nothing is applied unless the entry is signed.** ``reviewed_by`` and
   ``reviewed_at`` must both be present and non-empty. Preparing the manifest
   leaves them null, so the script does nothing until a person has actually
   reviewed the entry — the flag is the whole point of the manifest being
   "explicitly reviewed".
5. **Entries whose action is not ``reject`` are never executed.** ``none`` and
   ``report_only`` exist so a reviewer can record a decision (duplicate review,
   metadata defect) without this script having an opinion about it.

Why ``reject`` and not something gentler: from the published state the state
machine offers exactly two moves, ``REJECTED`` and ``PENDING_REVIEW``, and
reaching ``PENDING_REVIEW`` requires an actual field edit (``correct``) or a
misleading ``submitted`` audit row (``record_submission``). Rejection is the
only transition that quarantines a record without inventing a change that did
not happen.

    python scripts/apply_quarantine_manifest.py                      # dry run
    python scripts/apply_quarantine_manifest.py --execute --actor me
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Runnable as `python scripts/apply_quarantine_manifest.py` from anywhere: the
# repository root must be importable without the caller setting PYTHONPATH.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "audit" / "2026-10-15_quarantine_manifest.json"

CATEGORIES = {"A", "B", "C", "D"}
ACTIONS = {"reject", "none", "report_only"}
EXECUTABLE_ACTIONS = {"reject"}
REQUIRED_ENTRY_FIELDS = (
    "scholarship_id", "current_status", "category", "title",
    "official_url", "proposed_action", "confidence", "human_review_required",
    "evidence",
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PREFLIGHT = 3


class ManifestError(ValueError):
    """The manifest cannot be acted on as written."""


# ---------------------------------------------------------------- validation


def load_manifest(path: Path) -> dict:
    """Read the manifest, failing loudly rather than substituting defaults."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ManifestError("manifest must be an object with an 'entries' array")
    return data


def validate_manifest(manifest: dict) -> list[str]:
    """Return every structural problem, so a reviewer sees them all at once.

    Each entry is checked field by field rather than bailing at the first
    problem: a reviewer fixing a manifest wants the whole list, not one error
    per run.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(manifest["entries"]):
        where = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: not an object")
            continue

        missing = [name for name in REQUIRED_ENTRY_FIELDS if name not in entry]
        if missing:
            errors.append(f"{where}: missing field(s) {', '.join(missing)}")

        key = None
        if "scholarship_id" in entry:
            try:
                key = str(uuid.UUID(str(entry["scholarship_id"])))
            except (ValueError, AttributeError, TypeError):
                errors.append(
                    f"{where}: scholarship_id {entry['scholarship_id']!r} is not a UUID"
                )
        if key:
            if key in seen:
                errors.append(f"{where}: duplicate scholarship_id {key}")
            seen.add(key)

        if "category" in entry and entry["category"] not in CATEGORIES:
            errors.append(f"{where}: category {entry['category']!r} not in {sorted(CATEGORIES)}")
        if "proposed_action" in entry and entry["proposed_action"] not in ACTIONS:
            errors.append(
                f"{where}: proposed_action {entry['proposed_action']!r} not in {sorted(ACTIONS)}"
            )
        if "current_status" in entry and not entry["current_status"]:
            errors.append(f"{where}: current_status is empty")
        if "evidence" in entry and not entry["evidence"]:
            errors.append(f"{where}: no evidence recorded")
        if "human_review_required" in entry and not isinstance(
            entry["human_review_required"], bool
        ):
            errors.append(f"{where}: human_review_required must be a boolean")
        if entry.get("proposed_action") in EXECUTABLE_ACTIONS and not entry.get("official_url"):
            errors.append(f"{where}: executable action needs official_url for evidence_url")
    return errors


def is_signed(entry: dict) -> bool:
    """A reviewer has taken responsibility for this entry."""
    return bool(str(entry.get("reviewed_by") or "").strip()) and bool(
        str(entry.get("reviewed_at") or "").strip()
    )


# ------------------------------------------------------------------ planning


@dataclass
class EntryPlan:
    scholarship_id: str
    title: str
    category: str
    action: str
    verdict: str          # APPLY | ALREADY_DONE | SKIP_UNSIGNED | SKIP_NOT_EXECUTABLE | PROBLEM
    detail: str = ""
    current_status: str = ""
    human_review_required: bool = False
    signed_by: str = ""


@dataclass
class Plan:
    baseline: dict[str, int] = field(default_factory=dict)
    entries: list[EntryPlan] = field(default_factory=list)

    @property
    def problems(self) -> list[EntryPlan]:
        return [e for e in self.entries if e.verdict == "PROBLEM"]

    @property
    def applicable(self) -> list[EntryPlan]:
        return [e for e in self.entries if e.verdict == "APPLY"]

    @property
    def already_done(self) -> list[EntryPlan]:
        return [e for e in self.entries if e.verdict == "ALREADY_DONE"]


def status_counts(session) -> dict[str, int]:
    """Public counts, reported before and after so a run is self-evidencing.

    Every known state is present with a zero when no row carries it. A report
    that omits `approved` because there are zero approved records is not a
    smaller report, it is a different shape — and a caller doing
    `before[APPROVED] + 1` fails on an empty database for no useful reason.
    """
    from sqlalchemy import func

    from database.models.scholarship import Scholarship
    from services.review.service import ReviewStatus

    states = (
        ReviewStatus.PENDING_REVIEW,
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.NEEDS_CORRECTION,
    )
    counts = {state: 0 for state in states}
    rows = session.query(
        Scholarship.extraction_status, func.count(Scholarship.scholarship_id)
    ).group_by(Scholarship.extraction_status).all()
    counts.update({state: int(count) for state, count in rows})
    return counts


def outcome_status(action: str) -> str | None:
    """The state an action leaves a record in, for idempotent re-runs."""
    if action == "reject":
        return "rejected"
    return None


def build_plan(session, manifest: dict) -> Plan:
    """Resolve every manifest entry against the live records. Reads only."""
    from database.models.scholarship import Scholarship

    plan = Plan(baseline=status_counts(session))

    for entry in manifest["entries"]:
        plan.entries.append(_resolve_entry(session, Scholarship, entry))
    return plan


def _resolve_entry(session, Scholarship, entry: dict) -> EntryPlan:
    scholarship_id = str(uuid.UUID(str(entry["scholarship_id"])))
    action = entry["proposed_action"]
    human_review = bool(entry["human_review_required"])

    record = session.get(Scholarship, uuid.UUID(scholarship_id))
    if record is None:
        return EntryPlan(
            scholarship_id, entry.get("title", ""), entry["category"], action,
            "PROBLEM", "record not found", "missing", human_review,
        )

    status = record.extraction_status or ""
    if action not in EXECUTABLE_ACTIONS:
        return EntryPlan(
            scholarship_id, entry.get("title", ""), entry["category"], action,
            "SKIP_NOT_EXECUTABLE",
            "decision recorded only; no state change proposed",
            status, human_review,
        )

    if status == outcome_status(action):
        # Already where the manifest wants it: idempotent, not an error.
        return EntryPlan(
            scholarship_id, entry.get("title", ""), entry["category"], action,
            "ALREADY_DONE", f"already {status}", status, human_review,
        )

    if status != entry["current_status"]:
        return EntryPlan(
            scholarship_id, entry.get("title", ""), entry["category"], action,
            "PROBLEM",
            f"manifest expects {entry['current_status']!r} but record is {status!r}",
            status, human_review,
        )

    if not is_signed(entry):
        return EntryPlan(
            scholarship_id, entry.get("title", ""), entry["category"], action,
            "SKIP_UNSIGNED",
            "no reviewed_by/reviewed_at — a person must sign this entry first",
            status, human_review,
        )

    return EntryPlan(
        scholarship_id, entry.get("title", ""), entry["category"], action,
        "APPLY", "", status, human_review,
        signed_by=str(entry["reviewed_by"]),
    )


# ------------------------------------------------------------------ execution


def _reason_for(entry: dict, signed_by: str, manifest_version: object) -> str:
    """A rejection reason a later reader can act on: why, from where, who."""
    evidence = entry.get("evidence") or []
    first = ""
    if evidence and isinstance(evidence[0], dict):
        first = str(evidence[0].get("fact", ""))
    if len(first) > 300:
        first = first[:297] + "..."
    return (
        f"quarantine manifest v{manifest_version} category {entry['category']} "
        f"confidence {entry['confidence']}, signed by {signed_by}: {first}"
    )


def apply_plan(session, manifest: dict, plan: Plan, actor: str) -> dict[str, int]:
    """Apply every signed, status-verified entry through ReviewService."""
    from database.models.scholarship_review_action import ReviewSource
    from services.review.service import ReviewService

    entries = {
        str(uuid.UUID(str(e["scholarship_id"]))): e for e in manifest["entries"]
    }

    service = ReviewService(session)
    applied = 0
    for plan_entry in plan.applicable:
        entry = entries[plan_entry.scholarship_id]
        service.reject(
            plan_entry.scholarship_id,
            actor=actor,
            reason=_reason_for(entry, plan_entry.signed_by, manifest.get("manifest_version")),
            source=ReviewSource.SYSTEM,
            evidence_url=entry.get("official_url"),
        )
        applied += 1
    if applied:
        session.commit()
    else:
        session.rollback()
    return {"applied": applied}


def run(argv: list[str], *, session_factory=None) -> int:
    """Parse, preflight and (optionally) apply.

    ``session_factory`` exists so tests can drive the same code path against a
    rolled-back fixture session. When it is omitted the script opens and owns
    its own session, and closes it; a session supplied by a caller belongs to
    that caller, so it is left alone.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--execute", action="store_true",
        help="apply the signed entries. Default is a read-only dry run.",
    )
    parser.add_argument("--actor", default="catalogue-trust-sprint",
                        help="actor recorded on the audit row when --execute is used")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"INVALID MANIFEST: {exc}", file=sys.stderr)
        return EXIT_USAGE

    errors = validate_manifest(manifest)
    if errors:
        print("INVALID MANIFEST — nothing will be applied:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return EXIT_USAGE

    print(f"manifest: {args.manifest}")
    print(f"mode    : {'EXECUTE' if args.execute else 'DRY RUN (no writes)'}")

    own_session = session_factory is None
    if own_session:
        from database.session import SessionLocal

        session = SessionLocal()
    else:
        session = session_factory()
    try:
        baseline = status_counts(session)
        print("counts before:")
        for state in sorted(baseline):
            print(f"  {state:18s} {baseline[state]}")

        plan = build_plan(session, manifest)

        for entry in plan.entries:
            marker = {
                "APPLY": "APPLY  ",
                "ALREADY_DONE": "DONE   ",
                "SKIP_UNSIGNED": "UNSIGNED",
                "SKIP_NOT_EXECUTABLE": "REPORT ",
                "PROBLEM": "PROBLEM",
            }[entry.verdict]
            review = " [HUMAN REVIEW REQUIRED]" if entry.human_review_required else ""
            detail = f" — {entry.detail}" if entry.detail else ""
            signed = f" signed={entry.signed_by}" if entry.signed_by else ""
            print(
                f"{marker} {entry.category} {entry.action:13s} "
                f"{entry.scholarship_id} {entry.title[:56]!r}{review}{signed}{detail}"
            )

        if plan.problems:
            print(
                f"\nPREFLIGHT FAILED: {len(plan.problems)} record(s) are not in the "
                "state the manifest expects. Nothing was applied.",
                file=sys.stderr,
            )
            return EXIT_PREFLIGHT

        skipped = len(plan.entries) - len(plan.applicable) - len(plan.already_done)
        if not args.execute:
            print(
                f"\ndry run complete: {len(plan.applicable)} entr(ies) would be "
                f"rejected, {len(plan.already_done)} already applied, {skipped} "
                "skipped. Nothing was written."
            )
            print("counts after: unchanged (dry run)")
            return EXIT_OK

        if not plan.applicable:
            print(
                f"\nnothing to apply: {len(plan.already_done)} already applied, "
                f"{skipped} not signed or not executable."
            )
            after = status_counts(session)
            print("counts after:")
            for state in sorted(after):
                print(f"  {state:18s} {after[state]}")
            return EXIT_OK

        result = apply_plan(session, manifest, plan, args.actor)
        after = status_counts(session)
        print(f"\napplied {result['applied']} rejection(s) as actor {args.actor!r}")
        print("counts after:")
        for state in sorted(after):
            delta = after[state] - baseline.get(state, 0)
            suffix = f"  ({delta:+d})" if delta else ""
            print(f"  {state:18s} {after[state]}{suffix}")
        return EXIT_OK
    finally:
        if own_session:
            session.close()


def main(argv: list[str]) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
