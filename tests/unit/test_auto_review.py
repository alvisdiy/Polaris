"""The deterministic review pass: what it may decide, and what it must not."""

from __future__ import annotations

from services.review.auto_review import APPROVE, HOLD, REJECT, decide


def _decide(**overrides):
    base = dict(
        name="Chevening Scholarship 2027",
        provider_name="Foreign, Commonwealth & Development Office",
        official_page_url="https://www.chevening.org/scholarships/",
        publishable=True,
        blocking=[],
        name_accepted=True,
        duplicate_of_approved=False,
        page_text="Applications open until 5 November 2026.",
    )
    base.update(overrides)
    return decide(**base)


class TestApprove:
    def test_a_record_that_passed_every_gate_is_published(self):
        assert _decide().action == APPROVE

    def test_a_missing_degree_no_longer_blocks_publication(self):
        """Degree is a soft field; the gate does not report it as blocking."""
        decision = _decide(publishable=True, blocking=[])
        assert decision.action == APPROVE

    def test_approval_names_the_rule_that_allowed_it(self):
        decision = _decide()
        assert decision.code == "passed_all_gates"


class TestReject:
    def test_a_duplicate_of_a_published_record_is_rejected(self):
        decision = _decide(duplicate_of_approved=True)
        assert decision.action == REJECT
        assert decision.code == "duplicate"

    def test_an_aggregator_page_is_rejected(self):
        decision = _decide(official_page_url="https://www.wemakescholars.com/scholarship/1")
        assert decision.action == REJECT
        assert decision.code == "not_official_source"

    def test_a_generic_fee_policy_is_rejected(self):
        decision = _decide(name="Tuition Reduction and Exemption System")
        assert decision.action == REJECT
        assert decision.code == "generic_name"

    def test_administration_is_not_a_scholarship(self):
        decision = _decide(name="Government Grants Managed Service (GGMS)")
        assert decision.action == REJECT
        assert decision.code == "not_a_programme"

    def test_a_test_fixture_is_never_published(self):
        decision = _decide(name="MEXT Scholarship (Test)")
        assert decision.action == REJECT
        assert decision.code == "test_record"

    def test_a_job_board_provider_is_rejected(self):
        decision = _decide(
            provider_name="Find a PhD",
            official_page_url="https://www.jobs.ac.uk/job/DTB328/x",
        )
        assert decision.action == REJECT

    def test_a_closed_round_is_rejected_even_when_complete(self):
        decision = _decide(
            page_text="This call is closed for the 2026 cycle. Applications open again in 2027."
        )
        assert decision.action == REJECT
        assert decision.code == "closed_cycle"


class TestHold:
    def test_a_missing_required_field_holds_with_the_gate_reason(self):
        decision = _decide(publishable=False, blocking=["identity"])
        assert decision.action == HOLD
        assert decision.code == "incomplete"
        assert "identity" in decision.reason

    def test_a_hostname_provider_holds_for_identity_work(self):
        decision = _decide(provider_name="sysu.edu.cn")
        assert decision.action == HOLD
        assert decision.code == "provider_identity"

    def test_a_page_title_holds_rather_than_publishing_a_dirty_name(self):
        decision = _decide(
            name="（公財）日本国際教育支援協会 2022.5.12掲載 - 筑波大学"
        )
        assert decision.action == HOLD
        assert decision.code == "name_hygiene"

    def test_a_clean_name_with_a_year_is_not_dirty(self):
        assert _decide(name="SOAS Grant 2026/27").action == APPROVE
