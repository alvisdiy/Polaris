"""URL normalization and hashing utilities for discovery deduplication."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlparse, urlunparse

# Tracking params stripped during canonicalization
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "referrer",
}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for deduplication.

    - lowercase scheme/host
    - strip default ports, fragments, tracking params
    - strip default trailing slashes so canonical-equivalent URLs such as
      ``https://host/`` and ``https://host`` compare equal
    - sort remaining query params for stable comparison
    - stable under round-tripping: canonicalizing a canonical URL yields the same
      string
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

    # Strip the default trailing slash on any path, including the bare root. That
    # makes ``https://host/`` and ``https://host`` canonicalize to the same string,
    # which is what the dedup in `acquisition_service` depends on.
    path = path.rstrip("/")

    if path == "":
        path = "/"

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


#: CMS routes that render one record. The record's identity lives in the query
#: (``view.do?seq=759978``), so the path alone names nothing.
_VIEWER_ROUTE_STEMS = frozenset({
    "view", "detail", "read", "bbs", "board", "post", "article",
})

#: Query parameters that carry a record id on the CMSs used by ministries and
#: universities in the target countries. Only when the value is numeric.
_DETAIL_ID_QUERY_KEYS = frozenset({
    "seq", "no", "num", "id", "idx", "nseq", "b_idx", "board_seq",
    "article", "articleid", "article_id", "articleno", "docid", "contentid",
})

#: One record's id as the final path segment: ``2026917``, ``fg202610135``,
#: ``-202610137``. Three digits is the shortest id length seen on real sources;
#: shorter numbers are far more often a page number than a record.
_ID_SEGMENT_PATTERN = re.compile(r"^-?[a-z]{0,4}\d{3,}$")


def _segment_stem(segment: str) -> str:
    """The final path segment without a document extension."""
    stem = (segment or "").casefold()
    for ext in (".html", ".htm", ".shtml", ".php", ".jsp", ".aspx", ".do"):
        if stem.endswith(ext):
            return stem[: -len(ext)]
    return stem


def _query_record_id(url: str) -> str:
    """The single numeric record id in a URL's query, if it has exactly one."""
    query = urlparse(url).query
    if not query:
        return ""
    try:
        pairs = parse_qs(query, keep_blank_values=False)
    except ValueError:
        return ""
    hits = [
        key for key, values in pairs.items()
        if key.casefold() in _DETAIL_ID_QUERY_KEYS and values and values[0].isdigit()
    ]
    # One id among a couple of parameters is a record. Several ids, or an id
    # mixed with paging and search state, is a results view.
    if len(hits) == 1 and len(pairs) <= 2:
        return hits[0]
    return ""


def is_detail_record_url(url: str) -> bool:
    """Whether the URL addresses one record on the publisher's own CMS.

    Structural, not a site list. Two shapes cover the official sources that
    failed the 2026-10 live run: an id as the final path segment
    (``/pg/2026917.html``, 1,415 of them on one university listing) and an id
    in the query of a viewer route (``/brd/m_11417/view.do?seq=759978``, the
    MOFA Korea announcement pages). Neither URL contains the word
    "scholarship", which is why a keyword gate over the href alone returned
    zero candidates on those pages.

    Being a record says nothing about *what* the record is. This is an
    admission filter for discovery, never an eligibility decision: the
    classifier still decides whether the record is a scholarship.
    """
    parsed = urlparse(url)
    segments = [s for s in (parsed.path or "").split("/") if s]
    record_query = _query_record_id(url)
    if segments:
        stem = _segment_stem(segments[-1])
        if stem and _ID_SEGMENT_PATTERN.match(stem):
            return True
        if stem in _VIEWER_ROUTE_STEMS and record_query:
            return True
    return bool(record_query and segments)


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
