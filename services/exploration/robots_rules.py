"""robots.txt evaluation for discovery.

The standard library's ``urllib.robotparser`` returns the *first* matching
rule (Python 3.11), not the most specific one. A site that publishes the
perfectly ordinary::

    User-agent: *
    Disallow: /
    Allow: /en/

is therefore read as "nothing is allowed", including the English section the
site explicitly opened. That difference decides whether Polaris can read a
scholarship page at all, so the rule is implemented here:

* group selection: a named group wins over ``*``;
* within a group, the **longest matching pattern** wins;
* equal-length ``Allow`` beats ``Disallow``;
* ``*`` matches any run of characters, a trailing ``$`` anchors the end;
* an absent or unparsable robots.txt means "not forbidden".

The parsing is deliberately small: robots.txt is a line format, and this
module handles the directives that decide a fetch (``User-agent``,
``Allow``, ``Disallow``). It is not a general-purpose crawler framework.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit


class _Rule:
    __slots__ = ("allow", "pattern", "regex")

    def __init__(self, allow: bool, pattern: str) -> None:
        self.allow = allow
        self.pattern = pattern
        self.regex = _compile(pattern)

    def matches(self, path: str) -> bool:
        return self.regex.match(path) is not None


class _Group:
    __slots__ = ("agents", "rules")

    def __init__(self) -> None:
        self.agents: list[str] = []
        self.rules: list[_Rule] = []


def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a robots pattern into a prefix (or end-anchored) regex."""
    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    expression = ".*".join(re.escape(part) for part in core.split("*"))
    return re.compile("^" + expression + ("$" if anchored else ""))


def parse(text: str) -> list[_Group]:
    """Parse robots.txt into groups of rules."""
    groups: list[_Group] = []
    current: _Group | None = None
    in_agent_block = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if current is None or not in_agent_block:
                current = _Group()
                groups.append(current)
                in_agent_block = True
            if value:
                current.agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if current is None:
                continue
            in_agent_block = False
            # An empty Disallow means "allow everything" — it is the absence
            # of a restriction, not a rule that denies the root.
            if key == "disallow" and not value:
                continue
            if not value:
                continue
            current.rules.append(_Rule(key == "allow", value))

    return groups


def _token(user_agent: str) -> str:
    """The product token of a User-Agent header ('PolarisBot/0.2 (...)' → 'polarisbot')."""
    return user_agent.split("/")[0].strip().lower()


def _select_group(groups: list[_Group], token: str) -> _Group | None:
    """Pick the group that applies.

    A named group beats ``*``. Matching is on the product token, so
    ``PolarisBot`` matches the header Polaris sends, while ``Googlebot`` does
    not.
    """
    for group in groups:
        for agent in group.agents:
            if agent != "*" and (agent == token or token.startswith(agent)):
                return group
    for group in groups:
        if "*" in group.agents:
            return group
    return None


class RobotsRules:
    """A parsed robots.txt, evaluated with longest-match precedence."""

    __slots__ = ("_groups",)

    def __init__(self, groups: list[_Group]) -> None:
        self._groups = groups

    @classmethod
    def from_text(cls, text: str) -> "RobotsRules":
        return cls(parse(text))

    def allows(self, user_agent: str, url: str) -> bool:
        """Whether ``user_agent`` may fetch ``url``."""
        path = urlsplit(url).path or "/"
        group = _select_group(self._groups, _token(user_agent))
        if group is None:
            return True

        best: _Rule | None = None
        for rule in group.rules:
            if not rule.matches(path):
                continue
            if best is None or len(rule.pattern) > len(best.pattern):
                best = rule
            elif len(rule.pattern) == len(best.pattern) and rule.allow:
                best = rule

        return True if best is None else best.allow
