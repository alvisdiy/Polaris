"""Funding amount as stated (semantics A) and the description excerpt.

The extractor admits a figure only when one sentence carries the amount,
its period, and a funding noun together. These tests pin that evidence
rule, the tuition-waiver exclusion, the never-sum rule for pages stating
both tuition and a stipend, and the controlled funding_period vocabulary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.domain.vocabulary import FUNDING_PERIOD, InvalidVocabularyValue, validate
from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.validator import validate as validate_extraction


@pytest.fixture
def client():
    return DeterministicLLMClient()


class TestFundingAmount:
    def test_monthly_stipend_with_duration(self, client):
        result = client._extract_funding_amount(
            "The scholarship provides a stipend of €2,100 per month for 24 months.", None
        )
        assert result["amount"] == Decimal("2100")
        assert result["currency"] == "EUR"
        assert result["period"] == "per_month"
        assert result["duration_months"] == 24
        assert "stipend" in result["statement"]

    def test_per_year_grant(self, client):
        result = client._extract_funding_amount("The grant is $10,000 per year.", None)
        assert result["amount"] == Decimal("10000")
        assert result["currency"] == "USD"
        assert result["period"] == "per_year"
        assert result["duration_months"] is None

    def test_one_off_grant(self, client):
        result = client._extract_funding_amount("A one-off grant of $5,000 is awarded.", None)
        assert result["period"] == "one_off"

    def test_stipend_wins_over_tuition_and_is_never_summed(self, client):
        result = client._extract_funding_amount(
            "Tuition fees are €5,000 per year and a living allowance of €800 per month is provided.",
            None,
        )
        assert result["amount"] == Decimal("800")
        assert result["period"] == "per_month"

    def test_tuition_cost_alone_is_not_an_award(self, client):
        assert (
            client._extract_funding_amount(
                "The programme costs €3,000 per semester in tuition fees.", None
            )
            is None
        )

    def test_tuition_waiver_has_no_amount(self, client):
        assert (
            client._extract_funding_amount(
                "The scholarship is a stipend of €900 per month.", "Tuition Waiver"
            )
            is None
        )

    def test_amount_without_period_is_not_admitted(self, client):
        assert client._extract_funding_amount("The grant is $10,000.", None) is None

    def test_money_without_funding_context_is_not_admitted(self, client):
        assert client._extract_funding_amount("Students pay €200 per month for housing.", None) is None

    def test_european_thousands_separator(self, client):
        result = client._extract_funding_amount("A stipend of €2.100 per month is paid.", None)
        assert result["amount"] == Decimal("2100")
        assert result["currency"] == "EUR"

    def test_full_payload_carries_amount_and_evidence(self, client):
        payload = client.extract_scholarship(
            "Brightpath Scholars Award. The scholarship provides a stipend of "
            "€2,100 per month for 24 months to outstanding students.",
            "https://example.org/brightpath",
            page_title="Brightpath Scholars Award",
        )
        assert payload["funding_amount"] == Decimal("2100")
        assert payload["funding_currency"] == "EUR"
        assert payload["funding_period"] == "per_month"
        assert payload["funding_duration_months"] == 24
        evidence = payload["_extraction"]["funding_amount_evidence"]
        assert evidence["amount"] == "2100"
        assert "stipend" in evidence["statement"]


class TestDescription:
    def test_first_substantive_paragraph(self, client):
        text = (
            "Short nav line\n"
            "This scholarship supports outstanding graduate students from all "
            "countries who wish to pursue research abroad each year."
        )
        assert client._extract_description(text).startswith("This scholarship supports")

    def test_no_substantive_paragraph_is_none(self, client):
        assert client._extract_description("Menu\nHome\nApply") is None

    def test_description_is_capped(self, client):
        text = "word " * 200
        assert len(client._extract_description(text)) <= 500


class TestFundingPeriodVocabulary:
    def test_periods_are_controlled(self):
        for period in ("total", "per_year", "per_month", "per_semester", "one_off"):
            assert FUNDING_PERIOD.is_valid(period)
        assert not FUNDING_PERIOD.is_valid("weekly")

    def test_validate_rejects_unknown_period(self):
        with pytest.raises(InvalidVocabularyValue):
            validate("funding_period", "weekly")


class TestExtractionValidator:
    def _doc(self, **overrides):
        fields = dict(
            scholarship_name="Brightpath Scholars Award",
            provider_name="Zephyr Education Trust",
            country="JP",
            funding_amount=Decimal("2100"),
            funding_currency="EUR",
            funding_period="per_month",
        )
        fields.update(overrides)
        return ExtractedDocument(
            document_id="doc-1",
            source_url="https://example.org/brightpath",
            scholarship=ExtractedScholarship(**fields),
        )

    def test_amount_with_currency_and_period_is_valid(self):
        report = validate_extraction(self._doc())
        assert not [i for i in report.issues if i.field.startswith("funding")]

    def test_amount_without_period_is_refused(self):
        report = validate_extraction(self._doc(funding_period=None))
        assert any(i.field == "funding_amount" for i in report.issues)

    def test_unknown_period_is_refused(self):
        report = validate_extraction(self._doc(funding_period="weekly"))
        assert any(i.field == "funding_period" for i in report.issues)

    def test_lowercase_currency_is_refused(self):
        report = validate_extraction(self._doc(funding_currency="eur"))
        assert any(i.field == "funding_currency" for i in report.issues)
