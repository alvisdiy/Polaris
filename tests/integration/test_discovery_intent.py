"""The golden discovery dataset, run against the real stored pages (M11 §18).

Same shape as the M10 extraction corpus: real official pages, hand-written
labels, and a pinned ``document_id`` per sample so a later re-fetch cannot
silently become the thing being tested.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.models.raw_document import RawDocument
from services.exploration.page_intent import PageIntent, classify_page_intent

pytestmark = pytest.mark.data

DATASET = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "discovery_golden.json").read_text(
        encoding="utf-8"
    )
)
SAMPLES = DATASET["samples"]


@pytest.fixture(scope="module")
def dataset() -> list[dict]:
    return SAMPLES


@pytest.fixture
def documents(session) -> dict[str, RawDocument]:
    """The exact capture each sample was labelled from."""
    found = {}
    for sample in SAMPLES:
        document = (
            session.query(RawDocument)
            .filter(RawDocument.document_id == sample["document_id"])
            .one_or_none()
        )
        if document is not None:
            found[sample["id"]] = document
    return found


@pytest.fixture
def verdicts(session, documents) -> dict[str, object]:
    """Classify each stored sample once; every test reads the same verdict."""
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument

    out = {}
    for sample in SAMPLES:
        document = documents.get(sample["id"])
        if document is None:
            continue
        cleaned = clean(
            LoadedDocument(
                document_id=str(document.document_id),
                source_id=str(document.source_id),
                source_url=sample["url"],
                content_type=document.content_type,
                raw_content=document.raw_content,
            )
        )
        out[sample["id"]] = classify_page_intent(
            url=sample["url"],
            page_title=cleaned.page_title,
            headings=cleaned.headings,
            anchors=cleaned.anchors,
            text=cleaned.clean_text,
        )
    return out


class TestTheDiscoveryDatasetIsHonest:
    def test_every_sample_explains_its_label(self, dataset):
        for sample in dataset:
            assert sample.get("why"), sample["id"]
            assert sample.get("expected_intent"), sample["id"]
            assert sample["url"].startswith("https://"), sample["id"]

    def test_every_sample_is_pinned_to_a_document_id(self, dataset):
        for sample in dataset:
            assert sample.get("document_id"), sample["id"]

    def test_the_set_covers_the_classes_that_change_acquisition(self, dataset):
        """A benchmark of only easy positives would not test the routing."""
        intents = {s["expected_intent"] for s in dataset}
        assert PageIntent.SCHOLARSHIP_DETAIL in intents
        assert PageIntent.SCHOLARSHIP_INDEX in intents
        assert PageIntent.SCHOLARSHIP_OVERVIEW in intents
        assert PageIntent.FAQ in intents

    def test_the_set_covers_several_ecosystems(self, dataset):
        hosts = {s["url"].split("/")[2] for s in dataset}
        assert len(hosts) >= 5, f"discovery benchmark is too narrow: {sorted(hosts)}"


class TestTheClassifierAgreesWithTheHumanLabels:
    def test_every_pinned_capture_is_still_stored(self, dataset, documents):
        """A sample whose document is gone must fail, not quietly skip."""
        missing = [s["id"] for s in dataset if s["id"] not in documents]
        assert missing == [], (
            f"golden discovery samples whose pinned document is not stored: {missing}"
        )

    def test_page_intent_matches(self, dataset, verdicts):
        wrong = []
        for sample in dataset:
            got = verdicts.get(sample["id"])
            if got is None or got.intent != sample["expected_intent"]:
                wrong.append(
                    f"{sample['id']}: expected {sample['expected_intent']}, "
                    f"got {getattr(got, 'intent', 'NOT CLASSIFIED')}"
                )
        assert wrong == [], (
            "classifier disagrees with the hand-written labels:\n  "
            + "\n  ".join(wrong)
        )

    def test_every_verdict_carries_its_evidence(self, dataset, verdicts):
        for sample in dataset:
            got = verdicts.get(sample["id"])
            if got is not None:
                assert got.evidence, sample["id"]


class TestTheRoutingPropertyAcquisitionDependsOn:
    def test_an_index_sample_is_followable(self, dataset, verdicts):
        for sample in dataset:
            if sample["expected_intent"] == PageIntent.SCHOLARSHIP_INDEX:
                assert verdicts[sample["id"]].is_discovery_surface, sample["id"]
                assert not verdicts[sample["id"]].is_detail, sample["id"]

    def test_a_detail_sample_is_extractable_and_not_followable(self, dataset, verdicts):
        for sample in dataset:
            if sample["expected_intent"] == PageIntent.SCHOLARSHIP_DETAIL:
                got = verdicts[sample["id"]]
                assert got.is_detail, sample["id"]
                assert not got.is_discovery_surface, sample["id"]

    def test_an_unknown_sample_yields_nothing_rather_than_a_guess(self, dataset, verdicts):
        """If a stored page ever does earn UNKNOWN, it must produce nothing.

        No sample currently does; the rule is kept because a future capture of
        a JavaScript-gated or truncated page is exactly where it will.
        """
        for sample in dataset:
            if sample["expected_intent"] == PageIntent.UNKNOWN:
                got = verdicts[sample["id"]]
                assert not got.is_detail, sample["id"]
                assert got.confidence == 0.0, sample["id"]
