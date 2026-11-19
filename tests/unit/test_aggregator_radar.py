"""The aggregator radar keeps its boundary: pointers in, aggregators out."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "harvest_aggregators.py"
spec = importlib.util.spec_from_file_location("harvest_aggregators", SCRIPT)
harvest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvest)


def test_a_link_to_the_provider_is_kept():
    html = """
    <a href="https://www.chevening.org/scholarships/">Apply</a>
    """
    links = harvest._official_links(
        "https://fullyscholarships.com/x/", html, "fullyscholarships.com"
    )
    assert links == ["https://www.chevening.org/scholarships/"]


def test_social_links_are_dropped():
    html = """
    <a href="https://www.facebook.com/share/1">Share</a>
    <a href="https://twitter.com/x">Tweet</a>
    <a href="https://bit.ly/abc">Short</a>
    """
    assert harvest._official_links("https://x.com/a/", html, "fullyscholarships.com") == []


def test_a_chain_to_another_aggregator_is_dropped():
    """The radar must not walk from one collector to the next."""
    html = '<a href="https://www.wemakescholars.com/scholarship/1">More</a>'
    assert harvest._official_links("https://x.com/a/", html, "fullyscholarships.com") == []


def test_a_link_back_to_the_aggregator_itself_is_dropped():
    html = '<a href="https://fullyscholarships.com/other-post/">Read more</a>'
    assert harvest._official_links("https://x.com/a/", html, "fullyscholarships.com") == []


def test_country_comes_from_the_host_suffix():
    assert harvest._country_for("www.upm.edu.my") == "MY"
    assert harvest._country_for("iso.sysu.edu.cn") == "CN"
    assert harvest._country_for("www.daad.de") == "DE"
    assert harvest._country_for("cscuk.fcdo.gov.uk") == "GB"


def test_a_known_host_without_a_country_suffix_is_known():
    assert harvest._country_for("www.chevening.org") == "GB"
    assert harvest._country_for("stipendiumhungaricum.hu") == "HU"


def test_an_unknown_host_is_not_guessed():
    assert harvest._country_for("example.com") is None
