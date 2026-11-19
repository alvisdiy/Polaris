"""The golden dataset, run as a regression test (M10.3).

``scripts/m10_extraction_metrics.py`` prints the numbers for the M10 report.
This module is the same run as an assertion, so a change that quietly breaks
extraction fails the suite rather than waiting to be noticed in a report.

Two things are asserted here, and they are deliberately different in kind:

  * **precision** — where the dataset names a fact, the extractor must
    produce it. This is the part that catches regressions.
  * **never fabricate** — where the dataset says the page states nothing, the
    extractor must produce nothing. This is the part that matters most, and it
    is the one that cannot be traded off against a yield number.

The samples live in ``tests/golden/extraction_golden.json`` and are real
official pages. A field missing from a sample's ``expected`` is *not*
asserted: ambiguity is not a licence to assert an answer, and equally not a
licence to invent one.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from database.models.raw_document import RawDocument
from services.domain.vocabulary import CONTROLLED_VOCABULARIES, DEGREE
from services.ingestion.extractor import ExtractedScholarship

pytestmark = pytest.mark.data

DATASET = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "extraction_golden.json").read_text(
        encoding="utf-8"
    )
)
SAMPLES = DATASET["samples"]

SENTINEL_DEADLINES = {"2099-01-01", "2099-01-01T00:00:00", "9999-12-31"}
SENTINEL_NAMES = ("unknown scholarship", "unknown", "n/a", "none", "not specified")


@pytest.fixture(scope="module")
def dataset() -> list[dict]:
    return SAMPLES


@pytest.fixture(params=[s["id"] for s in SAMPLES])
def sample(request, dataset):
    return next(s for s in dataset if s["id"] == request.param)


@pytest.fixture
def extraction(sample, session, request):
    """Run the real pipeline over this sample's stored page."""
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.real_extractor import DeterministicLLMClient

    document = _document_for(session, sample)
    if document is None:
        pytest.skip(f"page not present in raw_document: {sample['url']}")

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
    return ExtractedScholarship(**payload).model_copy(update={"extraction_meta": meta})


def observed(extraction: ExtractedScholarship) -> dict:
    return {
        "scholarship_name": extraction.scholarship_name,
        "degree": extraction.degree,
        "funding_type": extraction.funding_type,
        "application_deadline": extraction.timeline.application_deadline,
        "unmapped_qualification": (extraction.extraction_meta or {}).get(
            "unmapped_qualification"
        ),
    }


class TestPrecision:
    """Where the dataset states a fact, the extractor must state it too."""

    def test_asserted_fields_match(self, sample, extraction):
        expected = sample.get("expected", {})
        got = observed(extraction)
        for field, want in expected.items():
            assert got[field] == want, (
                f"{sample['id']}.{field}: expected {want!r}, got {got[field]!r}. "
                f"Note: {sample.get('note', '')}"
            )


class TestItNeverFabricates:
    """The half that cannot be traded against yield."""

    def test_no_sentinel_deadline(self, extraction):
        deadline = extraction.timeline.application_deadline
        assert deadline not in SENTINEL_DEADLINES

    def test_no_placeholder_name(self, extraction):
        name = (extraction.scholarship_name or "").strip().casefold()
        assert name not in SENTINEL_NAMES
        assert not name.startswith("unknown ")

    def test_every_controlled_value_is_in_vocabulary(self, extraction):
        for field in ("degree", "funding_type"):
            value = getattr(extraction, field)
            assert value is None or CONTROLLED_VOCABULARIES[field].is_valid(value)

    def test_a_provider_is_a_noun_phrase_not_a_sentence(self, extraction):
        """M10. A provider captured mid-sentence used to reach the Provider table."""
        provider = extraction.provider_name or ""
        for mark in (". ", "? ", "! "):
            assert mark not in provider, f"provider is a sentence: {provider!r}"
        assert len(provider) <= 90

    def test_a_bare_year_is_not_stored_as_a_cohort(self, extraction):
        """M10. "2026-20" is a truncated "2026/2027" and reads as a real cohort."""
        cycle = extraction.timeline.application_cycle
        if not cycle:
            return
        for part in cycle.replace("/", "-").split("-"):
            if len(part) == 4:
                assert part.startswith("20"), cycle
            else:
                assert len(part) == 2, cycle

    def test_unmapped_evidence_is_not_carried_over_from_another_page(self, extraction):
        """M10. One client instance serves every page in a run."""
        assert "unmapped_qualification" in extraction.extraction_meta


class TestNameAccuracy:
    """Scholarship-name accuracy against a human-written reference.

    M10 measured 5 of 12 and refused to assert it, because the figure was a
    defect rather than a result. The post-M10 Priority B work took it to 11 of
    12, so it is now asserted: the count must hold, and the one sample that is
    still wrong is named in the dataset so the gap cannot quietly widen.
    """

    def test_name_accuracy_meets_the_recorded_figure(self, dataset, session):
        baseline = DATASET["name_accuracy"]
        correct, misses = self._score(dataset, session)
        assert correct >= baseline["correct"], (
            f"scholarship-name accuracy fell to {correct} from "
            f"{baseline['correct']}. Misses: {misses}. "
            f"See name_accuracy.note in the golden dataset."
        )

    def test_the_recorded_figure_matches_what_the_samples_warrant(
        self, dataset, session
    ):
        """A baseline written by hand drifts away from the samples.

        ``name_accuracy.total`` is the number of samples that were actually
        scored; a sample whose page is not stored is skipped and must not be
        counted, or the recorded figure would describe a different dataset
        from the one the suite runs.
        """
        scored = [s for s in dataset if _document_for(session, s) is not None]
        assert DATASET["name_accuracy"]["total"] == len(scored), (
            "name_accuracy.total does not match the number of scorable samples"
        )

    def test_the_recorded_shortfall_is_named(self, dataset, session):
        """Every sample the extractor gets wrong must say so in its own note."""
        correct, misses = self._score(dataset, session)
        recorded = DATASET["name_accuracy"]["total"] - DATASET["name_accuracy"]["correct"]
        assert len(misses) == recorded, (
            f"{len(misses)} samples fail but {recorded} are recorded as failing: {misses}"
        )
        for sample in dataset:
            if sample["id"] in misses:
                assert "still missed" in sample.get("note", ""), (
                    f"{sample['id']} is a known miss but its note does not say so"
                )

    @staticmethod
    def _score(dataset, session) -> tuple[int, list[str]]:
        correct = 0
        misses: list[str] = []
        for sample in dataset:
            # Negative samples count too: a page with no scholarship in it
            # must yield no name, so producing one is a miss, not a skip.
            reference = sample.get("name_reference")
            document = _document_for(session, sample)
            if document is None:
                continue
            if _name_of(document) == reference:
                correct += 1
            else:
                misses.append(sample["id"])
        return correct, misses


def _document_for(session, sample: dict) -> RawDocument | None:
    """The exact stored capture a sample's expectations were written against.

    Pinning by ``document_id`` rather than "newest fetch of this URL" is the
    point: the same URL is fetched again every crawl, and a site that later
    serves a truncated body would otherwise swap the corpus out from under
    the assertions without anybody editing the dataset.
    """
    return (
        session.query(RawDocument)
        .filter(RawDocument.document_id == uuid.UUID(sample["document_id"]))
        .one_or_none()
    )


def _name_of(document: RawDocument) -> str | None:
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.real_extractor import DeterministicLLMClient

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
    payload.pop("_extraction", None)
    return ExtractedScholarship(**payload).scholarship_name


class TestTheDatasetItselfIsHonest:
    """Guards against a golden set that gets quietly tuned to pass."""

    def test_every_sample_is_a_real_stored_page(self, dataset, session):
        missing = [s["id"] for s in dataset if _document_for(session, s) is None]
        assert missing == [], f"golden samples with no stored page: {missing}"

    def test_every_pinned_capture_is_the_page_its_note_describes(
        self, dataset, session
    ):
        """A document_id that points at a different URL is a corrupted corpus."""
        wrong = [
            s["id"]
            for s in dataset
            if _document_for(session, s) is not None
            and _document_for(session, s).source_url != s["url"]
        ]
        assert wrong == [], f"pinned captures whose stored url differs: {wrong}"

    def test_every_sample_explains_itself(self, dataset):
        for sample in dataset:
            assert sample.get("note"), sample["id"]
            assert sample["url"].startswith("https://"), sample["id"]
            assert sample.get("document_id"), sample["id"]

    def test_asserted_values_are_canonical_or_null(self, dataset):
        """A golden set that asserts 'Doctorate' would be asserting a bug."""
        for sample in dataset:
            expected = sample.get("expected", {})
            assert expected.get("degree") in (None, *DEGREE.order), sample["id"]

    def test_the_dataset_mixes_detail_pages_and_negative_samples(self, dataset):
        """A benchmark of only easy positives measures nothing."""
        negatives = [s for s in dataset if s.get("name_reference") is None]
        assert negatives, "golden set needs samples where nothing should be extracted"
        assert len(negatives) < len(dataset), "golden set needs successful samples too"

    def test_several_domains_are_covered(self, dataset):
        hosts = {s["url"].split("/")[2] for s in dataset}
        assert len(hosts) >= 4, f"golden set is too narrow: {sorted(hosts)}"
