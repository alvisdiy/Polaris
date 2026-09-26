"""Unit tests for URL utilities (normalization, hashing, eTLD+1)."""

from services.exploration.url_utils import domain_of, normalize_url, registered_domain, url_hash


class TestNormalizeUrl:
    def test_strips_www_and_fragment(self):
        assert (
            normalize_url("https://WWW.Example.com/scholarships/?utm_source=x#top")
            == "https://example.com/scholarships"
        )

    def test_sorts_query_params(self):
        a = normalize_url("https://x.com/p?b=2&a=1")
        b = normalize_url("https://x.com/p?a=1&b=2")
        assert a == b

    def test_strips_tracking_params_only(self):
        assert normalize_url("https://x.com/p?gclid=1&id=5") == "https://x.com/p?id=5"

    def test_adds_scheme_when_missing(self):
        assert normalize_url("example.com/scholarships").startswith("https://")

    def test_collapses_duplicate_slashes(self):
        assert normalize_url("https://x.com//a///b") == "https://x.com/a/b"


class TestUrlHash:
    def test_stable_and_normalized(self):
        assert url_hash("https://www.x.com/a") == url_hash("https://x.com/a")
        assert url_hash("https://x.com/a") != url_hash("https://x.com/b")

    def test_sha256_hex(self):
        h = url_hash("https://x.com")
        assert len(h) == 64
        int(h, 16)  # valid hex


class TestRegisteredDomain:
    def test_multi_suffix_japan(self):
        assert registered_domain("www.gs.gist.ac.kr") == "gist.ac.kr"
        assert registered_domain("jasso.go.jp") == "jasso.go.jp"
        assert registered_domain("mext.go.jp") == "mext.go.jp"
        assert registered_domain("kyoto-u.ac.jp") == "kyoto-u.ac.jp"

    def test_multi_suffix_other_countries(self):
        assert registered_domain("anu.edu.au") == "anu.edu.au"
        assert registered_domain("www.ox.ac.uk") == "ox.ac.uk"
        assert registered_domain("pku.edu.cn") == "pku.edu.cn"
        assert registered_domain("lpdp.go.id") == "lpdp.go.id"

    def test_simple_two_label(self):
        assert registered_domain("daad.de") == "daad.de"
        assert registered_domain("example.com") == "example.com"

    def test_deep_subdomains(self):
        assert registered_domain("a.b.c.gist.ac.kr") == "gist.ac.kr"
        assert registered_domain("scholarships.harvard.edu") == "harvard.edu"

    def test_empty(self):
        assert registered_domain("") == ""


class TestDomainOf:
    def test_basic(self):
        assert domain_of("https://www.jasso.go.jp/en/scholarships/") == "jasso.go.jp"

    def test_invalid(self):
        assert domain_of("") == ""
