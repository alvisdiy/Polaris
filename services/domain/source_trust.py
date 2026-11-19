"""Which hosts may be treated as an official scholarship source.

Official-source-first is the core product rule. A third-party aggregator is
useful for *discovery* — it can name a programme Polaris has not seen — but it
is not the page a reader should be sent to verify, and it must never become
``official_page_url`` or a verified ``SourceRegistry`` row.

The list is deliberately small and explicit: hosts observed in the catalogue
that are listing businesses, not providers. It is not a reputation score, and
a host absent from it is not thereby "official" — the verifier still requires
an institutional domain for that.
"""

from __future__ import annotations

from urllib.parse import urlsplit

AGGREGATOR_HOSTS: frozenset[str] = frozenset(
    {
        "wemakescholars.com",
        "scholarshipbob.com",
        "globalscholarships.com",
        "scholarshipsads.com",
        "globaladmissions.com",
        "scholarshipshive.com",
        "globalscholarshiphub.org",
        "opportunitiesforyouth.org",
        "opportunitiescircle.com",
        "scholarships.com",
        "scholarshipdb.com",
        "fastweb.com",
        "educations.com",
        "studyportals.com",
        "mastersportal.com",
        "bachelorsportal.com",
        "phdportal.com",
        "findamasters.com",
        "findaphd.com",
        "topuniversities.com",
        "timeshighereducation.com",
        "prospects.ac.uk",
        "scholarship-positions.com",
        "scholars4dev.com",
        "studyabroad.com",
        "gooverseas.com",
    }
)


def host_of(url: str | None) -> str:
    """The bare host of a URL or host string (``www.`` stripped, lowercased)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or "").rstrip(".").lower()
    return host[4:] if host.startswith("www.") else host


def aggregator_host(url: str | None) -> str | None:
    """The aggregator domain this URL belongs to, or None.

    Subdomains match their parent: ``www.wemakescholars.com`` and
    ``blog.wemakescholars.com`` are the same publisher.
    """
    host = host_of(url)
    if not host:
        return None
    if host in AGGREGATOR_HOSTS:
        return host
    for known in AGGREGATOR_HOSTS:
        if host.endswith(f".{known}"):
            return known
    return None


def is_aggregator_host(url: str | None) -> bool:
    return aggregator_host(url) is not None


#: Platforms where anyone can publish. A scholarship page on YouTube is not the
#: provider's official page, and a video is not a source a reviewer can verify
#: a requirement against.
SOCIAL_HOSTS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "reddit.com",
        "whatsapp.com",
        "wa.me",
        "t.me",
        "telegram.me",
        "pinterest.com",
    }
)

BLOCKED_SOURCE_HOSTS: frozenset[str] = AGGREGATOR_HOSTS | SOCIAL_HOSTS


def blocked_source_host(url: str | None) -> str | None:
    """The listing/social domain this URL belongs to, or None.

    One function for the frontier's admission gate: whether a URL is an
    aggregator or a social platform, it is not an official source and must not
    consume a fetch or a review slot in country exploration.
    """
    return aggregator_host(url) or _match_host(url, SOCIAL_HOSTS)


def is_blocked_source_host(url: str | None) -> bool:
    return blocked_source_host(url) is not None


def _match_host(url: str | None, hosts: frozenset[str]) -> str | None:
    host = host_of(url)
    if not host:
        return None
    if host in hosts:
        return host
    for known in hosts:
        if host.endswith(f".{known}"):
            return known
    return None
