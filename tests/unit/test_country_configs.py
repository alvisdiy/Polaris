"""Unit tests for country exploration configs.

Regression guard for the 2026-11-24 review finding: ``BN.json``/``MY.json``
were uppercase on disk while ``load_country_config`` looks for
``{iso2.lower()}.json``, so Brunei and Malaysia silently failed to load on
case-sensitive filesystems (Linux / Docker / CI) while working on Windows.
Every config file must load, and its declared ISO2 must match its filename.
"""

from services.exploration.config_loader import (
    CONFIG_DIR,
    available_countries,
    load_country_config,
)


class TestCountryConfigs:
    def test_every_config_file_loads(self):
        countries = available_countries()
        assert len(countries) == 12
        for iso2 in countries:
            config = load_country_config(iso2)
            assert config.iso2.lower() == iso2
            assert config.country_name

    def test_config_filenames_are_lowercase(self):
        # The loader lowercases the ISO2 code; an uppercase filename is
        # unreachable on Linux even though it loads fine on Windows.
        assert all(p.name == p.name.lower() for p in CONFIG_DIR.glob("*.json"))

    def test_brunei_and_malaysia_load(self):
        # The two countries that were dead on Linux before the rename.
        assert load_country_config("bn").country_name == "Brunei"
        assert load_country_config("my").country_name == "Malaysia"

    def test_no_foreign_academic_suffix_in_signals(self):
        # A country's soft domain signals must belong to that country.
        # Malaysia's config previously carried ".ac.uk" (a copy-paste from
        # the UK config), which polluted its "official" signal with UK
        # domains. ".ac.uk" is legitimate only for GB itself.
        for iso2 in available_countries():
            config = load_country_config(iso2)
            if iso2 != "gb":
                assert ".ac.uk" not in config.soft_domain_signals
