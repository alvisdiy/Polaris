"""Provider names that are domain fragments, not organisations."""

from __future__ import annotations

from services.exploration.provider_resolver import is_noise_org_name


class TestDomainDerivedNames:
    def test_a_vowel_less_acronym_is_noise(self):
        # "Jpf" was stored as the provider for a Japan Foundation record.
        assert is_noise_org_name("Jpf")
        assert is_noise_org_name("jpf")

    def test_a_bare_hostname_is_noise(self):
        assert is_noise_org_name("jpf.go.jp")
        assert is_noise_org_name("www.jpf.go.jp")

    def test_real_acronyms_survive(self):
        # MIT, NUS and DAAD have vowels and are real organisations.
        assert not is_noise_org_name("MIT")
        assert not is_noise_org_name("NUS")
        assert not is_noise_org_name("DAAD")
        assert not is_noise_org_name("JASSO")

    def test_a_real_name_survives(self):
        assert not is_noise_org_name("The Japan Foundation")
        assert not is_noise_org_name("Japan Student Services Organization")
