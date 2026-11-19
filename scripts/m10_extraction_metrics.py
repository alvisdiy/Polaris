"""Extraction metrics against the golden dataset (M10.3 §15).

Runs the real pipeline — cleaner, extractor, validator, mapper, quality gates —
over the pages in ``tests/golden/extraction_golden.json`` and reports each
metric separately. There is deliberately no single "accuracy" number: a
pipeline can look excellent on names and be publishing wrong deadlines, and a
mean would hide exactly that.

    python scripts/m10_extraction_metrics.py
    python scripts/m10_extraction_metrics.py --verbose

Read-only with respect to the knowledge base: pages are cleaned and extracted
in memory, mapped to transient ORM objects, and discarded. Nothing is written.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.raw_document import RawDocument  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.ingestion.cleaner import clean  # noqa: E402
from services.ingestion.extractor import ExtractedScholarship  # noqa: E402
from services.ingestion.loader import LoadedDocument  # noqa: E402
from services.ingestion.real_extractor import DeterministicLLMClient  # noqa: E402
from services.ingestion.validator import validate  # noqa: E402
from services.scholarship.mapper import ScholarshipMapper  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "tests" / "golden" / "extraction_golden.json"

# Fields judged per sample. Each is judged on its own terms because they fail
# in different ways: a wrong name is cosmetic, a wrong deadline sends a
# student to a closed call.
JUDGED_FIELDS = (
    "scholarship_name",
    "degree",
    "funding_type",
    "application_deadline",
    "unmapped_qualification",
)


def load_dataset() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def extract_one(document: RawDocument) -> ExtractedScholarship | None:
    """Clean and extract exactly as the pipeline does."""
    cleaned = clean(
        LoadedDocument(
            document_id=str(document.document_id),
            source_id=str(document.source_id),
            source_url=document.source_url,
            content_type=document.content_type,
            raw_content=document.raw_content,
        )
    )
    payload = dict(
        DeterministicLLMClient().extract_scholarship(
            cleaned.clean_text,
            source_url=cleaned.source_url,
            page_title=cleaned.page_title,
            headings=tuple(cleaned.headings),
            anchors=tuple(cleaned.anchors),
            looks_like_index=cleaned.looks_like_index,
        )
    )
    meta = payload.pop("_extraction")
    try:
        return ExtractedScholarship(**payload).model_copy(
            update={"extraction_meta": meta}
        )
    except Exception:  # noqa: BLE001 — a schema failure is a result, not a crash
        return None


def observed(result: ExtractedScholarship | None) -> dict:
    """The extraction's answer in the same shape as a golden expectation."""
    if result is None:
        return {field: None for field in JUDGED_FIELDS}
    return {
        "scholarship_name": result.scholarship_name,
        "degree": result.degree,
        "funding_type": result.funding_type,
        "application_deadline": result.timeline.application_deadline,
        "unmapped_qualification": (result.extraction_meta or {}).get(
            "unmapped_qualification"
        ),
    }


def quality_of(session, result: ExtractedScholarship | None, document: RawDocument):
    """Map and gate the extraction, the way persistence would."""
    if result is None:
        return None
    from services.ingestion.orchestrator import _as_document

    class _Cleaned:
        document_id = str(document.document_id)
        source_url = document.source_url

    wrapped = _as_document(_Cleaned(), result.model_dump(mode="python"))
    report = validate(wrapped)
    if not report.is_valid:
        return None
    meta = dict(result.extraction_meta or {})
    meta.setdefault("document_id", str(document.document_id))
    meta.setdefault("origin", "exploration")
    stamped = result.model_copy(update={"extraction_meta": meta})
    try:
        mapped = ScholarshipMapper(session).to_orm(
            stamped, str(document.source_id), document_url=document.source_url
        )
    except ValueError:
        return None
    return mapped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        dataset = load_dataset()
        samples = dataset["samples"]
        per_field = {f: {"correct": 0, "wrong": 0, "asserted": 0} for f in JUDGED_FIELDS}
        name_accuracy = {"correct": 0, "total": 0}
        normalisation = {"checked": 0, "consistent": 0, "inconsistent": 0}
        provenance = {"checked": 0, "complete": 0, "incomplete": 0}
        vocab_violations, sentinels, sentence_providers = [], [], []
        refused_nameless: list[str] = []
        schema_failures = quality_failures = publishable = unknown_deadline = 0
        unknown_degree = unknown_funding = 0
        rows = []

        for sample in samples:
            document = (
                session.query(RawDocument)
                .filter(
                    RawDocument.document_id
                    == uuid.UUID(sample["document_id"])
                )
                .one_or_none()
            )
            if document is None:
                rows.append((sample["id"], "PAGE NOT STORED", {}))
                continue

            result = extract_one(document)
            if result is None:
                schema_failures += 1
                rows.append((sample["id"], "SCHEMA FAILURE", {}))
                continue

            got = observed(result)
            expected = sample.get("expected", {})
            misses = []
            # Names are measured against a reference answer rather than
            # asserted: the current figure is a reported defect, and the
            # dataset says so in name_accuracy.note.
            reference = sample.get("name_reference")
            if reference is not None:
                name_accuracy["total"] += 1
                name_accuracy["correct"] += 1 if got["scholarship_name"] == reference else 0
                if got["scholarship_name"] != reference:
                    misses.append(
                        f"scholarship_name: reference {reference!r}, got "
                        f"{got['scholarship_name']!r}"
                    )

            for field in JUDGED_FIELDS:
                if field not in expected:
                    continue
                if field not in expected:
                    continue
                per_field[field]["asserted"] += 1
                if got[field] == expected[field]:
                    per_field[field]["correct"] += 1
                else:
                    per_field[field]["wrong"] += 1
                    misses.append(f"{field}: expected {expected[field]!r}, got {got[field]!r}")

            # Controlled values must come from the domain vocabulary.
            for field, vocabulary in (
                ("degree", "degree"),
                ("funding_type", "funding_type"),
            ):
                value = got[field]
                if value is None:
                    continue
                from services.domain import vocabulary as vocab_module

                if not vocab_module.CONTROLLED_VOCABULARIES[vocabulary].is_valid(value):
                    vocab_violations.append(f"{sample['id']}.{field}={value!r}")

            # Sentinels: the values that must never appear in a stored record.
            if got["application_deadline"] == "2099-01-01":
                sentinels.append(f"{sample['id']}: deadline 2099-01-01")
            if (got["scholarship_name"] or "").casefold().startswith("unknown "):
                sentinels.append(f"{sample['id']}: placeholder name {got['scholarship_name']!r}")
            provider = result.provider_name or ""
            if any(mark in provider for mark in (". ", "? ", "! ")):
                sentence_providers.append(f"{sample['id']}: {provider!r}")

            # Normalisation: a recorded source term must differ from the value.
            terms = (result.extraction_meta or {}).get("source_terms") or {}
            for field, alias in terms.items():
                normalisation["checked"] += 1
                canonical = got.get(field)
                if canonical is None or alias.casefold() != str(canonical).casefold():
                    normalisation["consistent"] += 1
                else:
                    normalisation["inconsistent"] += 1

            mapped = quality_of(session, result, document)
            if mapped is None:
                # The mapper refuses a record with no name. On a page that is
                # not a scholarship that refusal is the correct outcome, not a
                # defect, so it is counted separately rather than inflating
                # the quality-failure figure.
                if (result.scholarship_name or "").strip():
                    quality_failures += 1
                else:
                    refused_nameless.append(sample["id"])
            else:
                entries = mapped.field_provenance or {}
                for field, entry in entries.items():
                    provenance["checked"] += 1
                    if entry.get("source_url") and entry.get("method") and entry.get("origin"):
                        provenance["complete"] += 1
                    else:
                        provenance["incomplete"] += 1
                report = mapped.quality_report or {}
                if report.get("publishable"):
                    publishable += 1

            if got["application_deadline"] is None:
                unknown_deadline += 1
            if got["degree"] is None:
                unknown_degree += 1
            if got["funding_type"] is None:
                unknown_funding += 1

            status = "ok" if not misses else "miss"
            rows.append((sample["id"], status, {"expected": expected, "got": got, "misses": misses}))

        report = {
            "samples": len(samples),
            "per_field": per_field,
            "name_accuracy_reference": name_accuracy,
            "name_accuracy_baseline": dataset.get("name_accuracy"),
            "normalisation": normalisation,
            "provenance": provenance,
        "schema_failures": schema_failures,
        "quality_failures": quality_failures,
        "refused_nameless": refused_nameless,
        "refused_nameless_note": (
            "Pages that produced no scholarship name, and which the mapper therefore "
            "declined to persist. Expected outcome, not a failure: a record with no "
            "identity must not enter the knowledge base."
        ),
            # Named for what it is: the gate a reviewer would have to
            # override. It is not an approval and nothing publishes from it.
            "passes_publication_gate": publishable,
            "unknown_deadline": unknown_deadline,
            "unknown_degree": unknown_degree,
            "unknown_funding": unknown_funding,
            "vocabulary_violations": vocab_violations,
            "sentinels": sentinels,
            "sentence_fragment_providers": sentence_providers,
            "rows": rows if args.verbose else None,
        }
        print(json.dumps(report, indent=2, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
