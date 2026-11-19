"""M10.8 repository-wide bypass audit.

Reads every Python file looking for the shapes that would let something other
than the review service publish, version or re-attribute a scholarship. The
question is not "is the code correct" — the test suite answers that — it is
"is there a second, unreviewed path to the same outcome".

Each rule names the bypass it closes and the existing control it relates to,
so an allowlist entry can be argued with rather than merely inherited.

Read-only. Run: ``python scripts/m10_bypass_audit.py``
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Production code only. Test fixtures legitimately build an approved row to
# exercise the boundary, and scanning them produces a wall of findings that
# says nothing about the shipped system. The M9.1 guard already excludes them
# for the same reason; this audit follows that scope and says so rather than
# quietly reporting a clean run it did not actually perform.
SCANNED = ("services", "scripts", "api", "database")

# Definitions, not call sites. The audit script contains the patterns it
# searches for, and the model file declares the row it describes.
IGNORED = {
    "scripts/m10_bypass_audit.py",
    "database/models/scholarship_version.py",
}

# Files allowed to name the published state, with the reason each is the
# smallest exception available. The first is the state machine itself.
ALLOWED_PUBLICATION_WRITERS = {
    "services/review/service.py": "the publication boundary; the only writer of the status",
    "scripts/seed_manual_scholarships.py": "bootstrap seed behind --approve-directly, writes no review action",
    "scripts/m91_verify_vocabulary.py": "verification script; sets a canonical degree and rolls back",
    "tests/integration/test_direct_approval_guard.py": "the guard's own allowlist and fixtures",
    "tests/integration/test_direct_approval_guard.py::ALLOWED": "documentation of the allowlist",
}

MACHINE_ACTORS = {"acquisition", "extraction", "llm", "crawler", "pipeline", "system", "seed"}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _python_files():
    for area in SCANNED:
        for path in sorted((ROOT / area).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if _relative(path) in IGNORED:
                continue
            yield path


def audit_publication_writes() -> list[dict]:
    """Any assignment of the published state outside the review service."""
    findings = []
    for path in _python_files():
        rel = _relative(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets, values = [], []
            if isinstance(node, ast.Assign):
                targets, values = list(node.targets), [node.value]
            elif isinstance(node, ast.AugAssign):
                targets, values = [node.target], [node.value]
            else:
                continue

            writes_status = any(
                isinstance(t, ast.Attribute) and t.attr == "extraction_status" for t in targets
            ) or any(
                isinstance(t, ast.Call)
                and any(kw.arg == "extraction_status" for kw in t.keywords)
                for t in targets
            )
            if not writes_status:
                continue
            for value in values:
                literal = (
                    isinstance(value, ast.Constant) and value.value == "approved"
                ) or (isinstance(value, ast.Attribute) and value.attr == "APPROVED")
                if literal and rel not in ALLOWED_PUBLICATION_WRITERS:
                    findings.append({"file": rel, "line": node.lineno, "rule": "direct approval"})
    return findings


def audit_review_reachability() -> list[dict]:
    """The ingestion layer must not be able to reach the review state machine.

    The containment claim for prompt injection is structural: a page cannot
    set a review state because nothing that reads a page can reach the thing
    that writes one.
    """
    findings = []
    for path in (ROOT / "services" / "ingestion").rglob("*.py"):
        if path.name in {"url_safety.py", "fetch_safety.py", "robots.py", "untrusted.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        for needle, rule in (
            ("ReviewService", "ingestion imports the review service"),
            ("from services.review", "ingestion imports services.review"),
            (".approve(", "ingestion calls an approval"),
            (".reject(", "ingestion calls a rejection"),
        ):
            if needle in text:
                findings.append(
                    {"file": _relative(path), "line": 0, "rule": f"{rule} ({needle})"}
                )
    return findings


def audit_raw_sql() -> list[dict]:
    """Direct SQL that writes a decision column."""
    patterns = {
        r"SET\s+extraction_status\s*=\s*'approved'": "SQL approval",
        r"INSERT\s+INTO\s+scholarship_version": "direct version write",
        r"UPDATE\s+scholarship\b[^;]*field_provenance": "direct provenance write",
        r"UPDATE\s+scholarship\b[^;]*extraction_status": "direct status write",
    }
    findings = []
    for path in _python_files():
        rel = _relative(path)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if rel in ALLOWED_PUBLICATION_WRITERS and "extraction_status" in line:
                continue
            for pattern, rule in patterns.items():
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append({"file": rel, "line": lineno, "rule": rule})
    return findings


def audit_version_allocation() -> list[dict]:
    """Only the review service may allocate a version number."""
    findings = []
    for path in _python_files():
        rel = _relative(path)
        text = path.read_text(encoding="utf-8")
        if "ScholarshipVersion(" not in text:
            continue
        # The audit script holds the pattern as a literal string, which would
        # otherwise report itself as a finding.
        if rel in IGNORED:
            continue
        if rel in {"services/review/service.py"}:
            continue
        # Acquisition writes a version for a *pending* record's freshness
        # refresh, which is curation of unpublished data, not publication.
        if rel == "services/exploration/acquisition_service.py":
            if "is_published(existing)" in text and "propose_candidate" in text:
                continue
        findings.append(
            {
                "file": rel,
                "line": 0,
                "rule": "allocates a ScholarshipVersion outside the review service",
            }
        )
    return findings


def audit_extraction_control_fields() -> list[dict]:
    """The extraction schema must have no field a page could answer with."""
    from services.ingestion.extractor import ExtractedScholarship

    forbidden = {
        "extraction_status", "verification_status", "review_state", "approved",
        "published", "is_verified", "match_score", "rank", "reviewed_by",
        "reviewed_at", "quality_report", "conflicts",
    }
    present = forbidden & set(ExtractedScholarship.model_fields)
    return [
        {"file": "services/ingestion/extractor.py", "line": 0,
         "rule": f"extraction schema exposes control field(s): {sorted(present)}"}
    ] if present else []


def audit_fetch_boundary() -> list[dict]:
    """No connector may fetch without the SafeFetch boundary."""
    findings = []
    for path in (ROOT / "services" / "ingestion" / "connectors").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "SafeFetch" in text:
            continue
        if re.search(r"\b(httpx|aiohttp|requests)\b", text):
            findings.append(
                {"file": _relative(path), "line": 0, "rule": "connector fetches without SafeFetch"}
            )
    return findings


def audit_review_service_is_the_only_approver() -> list[dict]:
    """No caller approves with a machine actor."""
    findings = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8").lower()
        for actor in MACHINE_ACTORS:
            if re.search(rf"\.approve\([^)]*actor\s*=\s*[\"']{actor}[\"']", text, re.DOTALL):
                findings.append(
                    {
                        "file": _relative(path),
                        "line": 0,
                        "rule": f"approves with machine actor {actor!r}",
                    }
                )
    return findings


def main() -> None:
    rules = (
        ("crawler/LLM -> approval", audit_publication_writes),
        ("acquisition -> published mutation", audit_review_reachability),
        ("direct SQL -> decision", audit_raw_sql),
        ("direct version", audit_version_allocation),
        ("LLM -> database publish", audit_extraction_control_fields),
        ("connector bypasses SafeFetch", audit_fetch_boundary),
        ("machine actor on approval", audit_review_service_is_the_only_approver),
    )
    total = 0
    for name, rule in rules:
        findings = rule()
        total += len(findings)
        marker = "OK " if not findings else "!! "
        print(f"{marker}{name}: {len(findings)}")
        for finding in findings:
            print(f"      {finding['file']}:{finding['line']} — {finding['rule']}")
    print(f"\nTOTAL FINDINGS: {total}")


if __name__ == "__main__":
    main()
