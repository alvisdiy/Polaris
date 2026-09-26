"""URL normalization and hashing utilities for discovery deduplication."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

# Tracking params stripped during canonicalization
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "referrer",
}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for deduplication.

    - lowercase scheme/host
    - strip default ports, fragments, tracking params
    - remove trailing slash on empty path
    - sort remaining query params for stable comparison
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if scheme == "https" and host.endswith(":443"):
        host = host[: -4]
    if scheme == "http" and host.endswith(":80"):
        host = host[: -3]

    path = unquote(parsed.path or "")
    # collapse duplicate slashes in path
    while "//" in path:
        path = path.replace("//", "/")
    # strip trailing slash (non-root)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    params = [
        (k.lower(), v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    params.sort()
    query = "&".join(f"{quote(k)}={quote(v)}" for k, v in params)

    return urlunparse((scheme, host, path, "", query, ""))


def url_hash(url: str) -> str:
    """Deterministic sha256 hash of the normalized URL (dedup key)."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def registered_domain(host: str) -> str:
    """Return the registered domain (eTLD+1) using an embedded public-suffix
    subset for Polaris's target countries. Safe fallback for unknown suffixes.

    Multi-suffix ccTLDs (.ac.jp, .go.id, .com.au, .ac.kr, .edu.cn, .co.uk …)
    are handled explicitly; everything else treats the last label as the TLD.
    Ambiguous multi-label suffixes (e.g. .ac.jp vs .tokyo.jp) resolve
    conservatively to the two-label form.
    """
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""

    parts = host.split(".")
    if len(parts) <= 2:
        return host

    # Two-label second-level suffixes used by institutional domains.
    second_level = {
        "ac", "ad", "co", "ed", "edu", "go", "gouv", "gov", "or", "org",
        "ne", "net", "com", "grp",
    }
    multi_suffix_tlds = {
        "jp", "kr", "id", "cn", "au", "uk", "fr", "in", "br", "mx", "za",
        "nz", "sg", "my", "th", "vn", "ph", "tw", "hk", "tr", "eg",
    }
    if len(parts) >= 3 and parts[-2] in second_level and parts[-1] in multi_suffix_tlds:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_of(url: str) -> str:
    """Host (lowercased, www-stripped) of a URL, or '' if unparseable."""
    try:
        host = urlparse(normalize_url(url)).netloc
        return host if host else ""
    except Exception:
        return ""
