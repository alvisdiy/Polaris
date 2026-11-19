"""robots.txt precedence rules.

Python 3.11's ``urllib.robotparser`` returns the first matching rule, so a
site publishing ``Disallow: /`` followed by ``Allow: /en/`` is read as a
blanket ban. These tests pin the behaviour Polaris relies on: longest match
wins, ``Allow`` wins a tie, and a named group beats ``*``.
"""

from __future__ import annotations

from services.exploration.robots_rules import RobotsRules

UA = "PolarisBot/0.2 (+https://polaris.example; discovery research)"


def rules(text: str) -> RobotsRules:
    return RobotsRules.from_text(text)


class TestLongestMatch:
    def test_allow_beats_a_broader_disallow(self):
        policy = rules("User-agent: *\nDisallow: /\nAllow: /en/\n")

        assert policy.allows(UA, "https://example.org/en/scholarships") is True
        assert policy.allows(UA, "https://example.org/admin") is False

    def test_a_longer_disallow_beats_a_shorter_allow(self):
        policy = rules("User-agent: *\nAllow: /docs\nDisallow: /docs/private\n")

        assert policy.allows(UA, "https://example.org/docs/public") is True
        assert policy.allows(UA, "https://example.org/docs/private/x") is False

    def test_equal_length_allow_wins(self):
        policy = rules("User-agent: *\nDisallow: /page\nAllow: /page\n")

        assert policy.allows(UA, "https://example.org/page") is True


class TestPatterns:
    def test_wildcard_matches_any_run(self):
        policy = rules("User-agent: *\nDisallow: /*/print\n")

        assert policy.allows(UA, "https://example.org/scholarship/print") is False
        assert policy.allows(UA, "https://example.org/scholarship/view") is True

    def test_trailing_dollar_anchors_the_end(self):
        policy = rules("User-agent: *\nDisallow: /*.pdf$\n")

        assert policy.allows(UA, "https://example.org/files/guide.pdf") is False
        assert policy.allows(UA, "https://example.org/files/guide.pdf.html") is True

    def test_empty_disallow_is_not_a_rule(self):
        policy = rules("User-agent: *\nDisallow:\n")

        assert policy.allows(UA, "https://example.org/anything") is True


class TestGroups:
    def test_a_named_group_beats_the_wildcard_group(self):
        policy = rules(
            "User-agent: Googlebot\n"
            "Disallow: /\n"
            "\n"
            "User-agent: *\n"
            "Allow: /\n"
        )

        assert policy.allows(UA, "https://example.org/scholarships") is True

    def test_the_named_group_applies_when_it_names_our_token(self):
        policy = rules(
            "User-agent: PolarisBot\n"
            "Disallow: /private\n"
            "\n"
            "User-agent: *\n"
            "Allow: /\n"
        )

        assert policy.allows(UA, "https://example.org/private/x") is False
        assert policy.allows(UA, "https://example.org/public") is True

    def test_consecutive_user_agent_lines_share_a_group(self):
        policy = rules(
            "User-agent: Googlebot\n"
            "User-agent: PolarisBot\n"
            "Disallow: /private\n"
        )

        assert policy.allows(UA, "https://example.org/private/x") is False
